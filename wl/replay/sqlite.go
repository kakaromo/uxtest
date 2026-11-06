package main

// 실제 SQLite 로 DB I/O 를 낸다. 측정 앱이 SQLite 에 맡기는 일(WAL·journal·checkpoint·fsync 순서)을 흉내 내지 않고 SQLite 가 직접 한다.
// 얼마나 쓰는지는 trace 에서 뽑은 page 수로 정한다 (gen_funcs.py dbmodel). 설정은 Android 기본값과 같다:
//   page 4096, WAL 은 synchronous=NORMAL, rollback 은 synchronous=FULL·DELETE. 자동 checkpoint 는 끄고 trace 의 시각에 직접 부른다.
// 한 행이 한 page 를 채워서, 행 N 개를 고치면 page N 개가 바뀐다.

import (
	"database/sql"
	"encoding/binary"
	"encoding/json"
	"errors"
	"fmt"
	"math/rand"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync/atomic"
	"time"

	"golang.org/x/sys/unix"
	_ "modernc.org/sqlite"
)

const (
	dbFlagSQLite   = 2
	dbFlagRollback = 4

	sqlWalCkpt  = 1    // WAL 에 쓰고 checkpoint: fsync(WAL) → DB 쓰기 → fsync(DB)
	sqlWalSync  = 2    // WAL 에 쓰고 WAL fsync 만
	sqlWalLazy  = 3    // WAL 에 쓰고 writeback 만 시작 (fsync 없음)
	sqlRollback = 4    // rollback journal transaction: journal 생성·fsync → DB 쓰기·fsync → journal 삭제
	sqlFreshWal = 0x10 // (flag) 원본 앱이 DB 를 닫았다 다시 열어 WAL 이 새로 생긴 transaction. 앞에서 닫고 다시 열고,
	// 첫 WAL sync 뒤 폴더를 fsync 한다 (SQLite 가 새 WAL 의 첫 sync 때 하는 것, UNIXFILE_DIRSYNC). f2fs 는 폴더 fsync 를 Checkpoint 로 처리한다

	rowBytes = 3900 // 한 행이 page 하나 (4096 - page·cell header)

	walPrefill = 256

	sqlSettle = 12 * time.Second // 재생 전 WAL 크기 (page). Android db_wal_truncate_size 1MB 와 같은 정도
)

var rowData = func() []byte {
	b := make([]byte, rowBytes)
	rand.New(rand.NewSource(7)).Read(b)
	return b
}()

func openDB(path string, rollback bool) (*sql.DB, error) {
	mode, syncm := "WAL", "NORMAL"
	if rollback {
		mode, syncm = "DELETE", "FULL"
	}
	d, err := sql.Open("sqlite", "file:"+path+"?_pragma=page_size(4096)&_pragma=journal_mode("+mode+")&_pragma=synchronous("+syncm+")&_pragma=wal_autocheckpoint(0)&_pragma=ignore_check_constraints(1)")
	if err != nil {
		return nil, err
	}
	d.SetMaxOpenConns(1)
	return d, d.Ping()
}

// 미리 채운 DB. 재생 앞에 만들고 끝까지 내려 둔다 (trace 밖)
func prepDB(path string, rows uint64, rollback bool) {
	for _, s := range []string{"", "-wal", "-shm", "-journal"} {
		os.Remove(path + s)
	}
	d, err := openDB(path, rollback)
	must(err)
	defer d.Close()
	_, err = d.Exec("CREATE TABLE t(id INTEGER PRIMARY KEY, v BLOB NOT NULL)")
	must(err)
	tx, err := d.Begin()
	must(err)
	st, err := tx.Prepare("INSERT INTO t(id, v) VALUES(?, ?)")
	must(err)
	for i := uint64(0); i < rows; i++ {
		_, err = st.Exec(int64(i), rowData)
		must(err)
	}
	st.Close()
	must(tx.Commit())
	if !rollback {
		_, err = d.Exec("PRAGMA wal_checkpoint(TRUNCATE)")
		must(err)
	}
}

type dbConn struct {
	d      *sql.DB
	st     *sql.Stmt
	rows   int64
	wal    int
	path   string
	rng    *rand.Rand
	q      chan req
	buf    []byte
	nonce  uint64
	tables []*realTbl

	// 실제 테이블의 양 맞추기 (WAL)
	shm       *os.File
	ratio     float64 // 행 동작 하나가 만드는 WAL frame 수 (재면서 고친다)
	debt      float64 // 아직 못 쓴 frame 수. 넘쳐 쓰면 음수
	pad       *sql.Stmt
	padRows   int64
	padNext   int64
	ckptFrame uint32
	txOps     int // transaction 하나의 행 동작 수 (dbwatch 의 행 동작 수 / commit 수)
	mainDebt  int // 원본이 DB 본체에 쓴 page 중 아직 안 쓴 수
	spec      *dbSpec
	reopens   int
}

var sqlReopens atomic.Int64

// 새 WAL 의 첫 sync 뒤 폴더 fsync 를 uxwl 이 직접 할지. SQLite 가 스스로 하므로 기본은 끔 (켜면 Checkpoint 가 두 번 난다, 11-06 ftrace)
var freshDirSync = false

// DB 를 닫고 다시 연다. 마지막 연결을 닫으면 SQLite 가 WAL 을 DB 로 옮기고 지우므로, 다음 transaction 이 WAL 을 새로 만든다
func (c *dbConn) reopen() error {
	if c.wal >= 0 {
		unix.Close(c.wal)
		c.wal = -1
	}
	if c.shm != nil {
		c.shm.Close()
		c.shm = nil
	}
	if err := c.d.Close(); err != nil {
		return err
	}
	d, err := openDB(c.path, false)
	if err != nil {
		return err
	}
	c.d, c.ckptFrame = d, 0
	if c.spec != nil {
		c.tables = prepTables(d, c.spec, c.rng)
		if c.pad != nil {
			if c.pad, err = d.Prepare(`UPDATE ` + padTable + ` SET v = ? WHERE id = ?`); err != nil {
				return err
			}
		}
	} else if c.st, err = d.Prepare("UPDATE t SET v = ? WHERE id = ?"); err != nil {
		return err
	}
	c.reopens++
	sqlReopens.Add(1)
	return nil
}

func (c *dbConn) syncDir() {
	if fd, err := unix.Open(filepath.Dir(c.path), unix.O_RDONLY|unix.O_DIRECTORY, 0); err == nil {
		unix.Fsync(fd)
		unix.Close(fd)
	}
}

// 양 맞추기 통계: 행 동작으로 쓴 frame, 채움 테이블로 쓴 frame
var sqlFramesReal, sqlFramesPad, sqlWarms atomic.Int64

const padTable = "_uxpad"

// WAL 에 쌓인 frame 수. C++ 로 옮기면 sqlite3_wal_hook 의 nFrame 으로 같은 값을 얻는다
func (c *dbConn) mxFrame() uint32 {
	if c.shm == nil {
		f, err := os.Open(c.path + "-shm")
		if err != nil {
			return 0
		}
		c.shm = f
	}
	var b [4]byte
	if _, err := c.shm.ReadAt(b[:], 16); err != nil { // WalIndexHdr.mxFrame
		return 0
	}
	return binary.LittleEndian.Uint32(b[:])
}

func frameDelta(before, after uint32) int {
	if after < before { // checkpoint 뒤 WAL 이 처음부터 다시 쓰였다
		return int(after)
	}
	return int(after - before)
}

// 채움 테이블의 행 n 개를 고친다. 한 행이 page 하나라 frame 이 정확히 n 개 나온다
func (c *dbConn) padUpdate(n int) error {
	if c.pad == nil || c.padRows == 0 || n <= 0 {
		return nil
	}
	for n > 0 {
		k := min(int64(n), c.padRows)
		tx, err := c.d.Begin()
		if err != nil {
			return err
		}
		st := tx.Stmt(c.pad)
		for i := int64(0); i < k; i++ {
			c.nonce++
			binary.LittleEndian.PutUint64(c.buf, c.nonce)
			if _, err = st.Exec(c.buf, c.padNext); err != nil {
				tx.Rollback()
				return err
			}
			c.padNext = (c.padNext + 1) % c.padRows
		}
		if err = tx.Commit(); err != nil {
			return err
		}
		n -= int(k)
	}
	return nil
}

// target 개의 WAL frame 을 쓴다: 먼저 실제 테이블 동작으로, 모자라면 채움 테이블로. 넘치면 다음 transaction 에서 뺀다
func (c *dbConn) realWal(target int) error {
	want := float64(target) + c.debt
	if want < 1 {
		c.debt = want
		return nil
	}
	// 앱처럼 작은 transaction 을 여러 번 낸다. 같은 page 도 commit 마다 WAL 에 다시 쓰이므로 작은 테이블에서도 실제 동작으로 양이 찬다
	a := c.mxFrame()
	got, done := 0, 0
	limit := int(4*want) + 16
	for float64(got) < want && done < limit {
		n := int((want-float64(got))/c.ratio + 0.999)
		n = max(1, min(n, c.txOps))
		if err := c.realOps(n); err == errNoTable {
			break // 쓸 테이블이 없으면 나머지는 채움 테이블로
		} else if err != nil {
			return err
		}
		b := c.mxFrame()
		d := frameDelta(a, b)
		a = b
		c.ratio = 0.9*c.ratio + 0.1*max(float64(d)/float64(n), 0.05)
		got += d
		done += n
	}
	sqlFramesReal.Add(int64(got))
	b := a
	if left := int(want) - got; left > 0 {
		if err := c.padUpdate(left); err != nil {
			return err
		}
		got2 := frameDelta(b, c.mxFrame())
		sqlFramesPad.Add(int64(got2))
		got += got2
	}
	c.debt = want - float64(got)
	return nil
}

// checkpoint 를 할지 정한다. 원본이 DB 본체에 쓴 page 수를 쌓아 두고, WAL 의 서로 다른 page 가 그 수에 맞을 때만 checkpoint 한다.
// 원본은 작은 Write 만 낸 자리에서 WAL 전체를 옮기면 DB 본체 Write 가 원본보다 많아진다. WAL 이 더 적으면 채움 테이블로 맞춘다
func (c *dbConn) ckptReady(main int) (bool, error) {
	c.mainDebt += main
	fd := c.walFd()
	if fd < 0 || c.mainDebt <= 0 {
		return false, nil
	}
	mx := c.mxFrame()
	if mx < c.ckptFrame {
		c.ckptFrame = 0
	}
	seen := map[uint32]bool{}
	var h [4]byte
	for i := c.ckptFrame; i < mx; i++ {
		if _, err := unix.Pread(fd, h[:], 32+int64(i)*(4096+24)); err == nil {
			seen[binary.BigEndian.Uint32(h[:])] = true
		}
	}
	if len(seen) > c.mainDebt*3/2+8 {
		return false, nil
	}
	if left := c.mainDebt - len(seen); left > 0 {
		if err := c.padUpdate(left); err != nil {
			return false, err
		}
		got := frameDelta(mx, c.mxFrame())
		sqlFramesPad.Add(int64(got))
		c.debt -= float64(got)
	}
	c.mainDebt = 0
	return true, nil
}

// pages 번 고치되 서로 다른 행은 uniq 개. 한 transaction 안에서 같은 page 는 WAL 에 한 번만 쓰이므로 uniq 개씩 나눠 commit 한다
func (c *dbConn) update(pages, uniq int) error {
	if uniq <= 0 {
		uniq = 1
	}
	if int64(uniq) > c.rows {
		uniq = int(c.rows)
	}
	ids := make([]int64, uniq)
	for i := range ids {
		ids[i] = c.rng.Int63n(c.rows)
	}
	for left := pages; left > 0; {
		n := min(left, uniq)
		tx, err := c.d.Begin()
		if err != nil {
			return err
		}
		for _, id := range ids[:n] {
			// 값을 바꿔야 한다. 같은 값이면 SQLite 가 page 를 고치지 않아 Write 가 나오지 않는다
			c.nonce++
			binary.LittleEndian.PutUint64(c.buf, c.nonce)
			if _, err = tx.Stmt(c.st).Exec(c.buf, id); err != nil {
				tx.Rollback()
				return err
			}
		}
		if err = tx.Commit(); err != nil {
			return err
		}
		left -= n
	}
	return nil
}

func (c *dbConn) walFd() int {
	if c.wal < 0 {
		if fd, err := unix.Open(c.path+"-wal", unix.O_RDWR, 0); err == nil {
			c.wal = fd
		}
	}
	return c.wal
}

func (c *dbConn) exec(r req) error {
	pages, uniq := int(r.off&0xffffffff), int(r.off>>32)
	fresh := r.ln&sqlFreshWal != 0
	r.ln &^= sqlFreshWal
	if fresh {
		if err := c.reopen(); err != nil {
			return err
		}
	}
	if c.tables != nil && c.pad != nil { // 실제 테이블 WAL: off 는 WAL frame 목표와 checkpoint page 목표
		if err := c.realWal(pages); err != nil {
			return err
		}
		if r.ln == sqlWalCkpt {
			ok, err := c.ckptReady(uniq)
			if err != nil {
				return err
			}
			if !ok {
				return nil
			}
		}
	} else if c.tables != nil {
		if err := c.realOps(pages); err != nil { // 실제 테이블 rollback: off 는 행 동작 수
			return err
		}
	} else if err := c.update(pages, uniq); err != nil {
		return err
	}
	switch r.ln {
	case sqlWalCkpt:
		if fresh {
			if fd := c.walFd(); fd >= 0 {
				unix.Fdatasync(fd)
			}
			if freshDirSync {
				c.syncDir()
			}
		}
		_, err := c.d.Exec("PRAGMA wal_checkpoint(PASSIVE)")
		c.ckptFrame = c.mxFrame()
		return err
	case sqlWalSync:
		if fd := c.walFd(); fd >= 0 {
			err := unix.Fdatasync(fd)
			if fresh && freshDirSync {
				c.syncDir()
			}
			return err
		}
	case sqlWalLazy:
		if fd := c.walFd(); fd >= 0 {
			return unix.SyncFileRange(fd, 0, 0, unix.SYNC_FILE_RANGE_WRITE)
		}
	}
	return nil
}

// 재생 동안 DB 마다 goroutine 하나가 순서대로 transaction 을 낸다
type sqlEngine struct {
	root  string
	files []tcFile
	conns map[uint32]*dbConn
	n, e  atomic.Uint64
	done  chan struct{}
	left  atomic.Int64
}

func newSQLEngine(root string, files []tcFile, reqs []req) *sqlEngine {
	s := &sqlEngine{root: root, files: files, conns: map[uint32]*dbConn{}, done: make(chan struct{})}
	dirty := false
	for _, r := range reqs {
		if r.op != opSQL || s.conns[r.file] != nil {
			continue
		}
		f := files[r.file]
		p := fpath(root, r.file)
		d, err := openDB(p, f.flags&dbFlagRollback != 0)
		must(err)
		var st *sql.Stmt
		if f.flags&dbFlagReal == 0 {
			st, err = d.Prepare("UPDATE t SET v = ? WHERE id = ?")
			must(err)
		}
		c := &dbConn{d: d, st: st, rows: int64(f.size / 4096), wal: -1, path: p, rng: rand.New(rand.NewSource(int64(r.file))), q: make(chan req, 4096), buf: append([]byte(nil), rowData...)}
		// 앱의 WAL 은 이미 있고 크기도 잡혀 있다. SQLite 는 마지막 연결을 닫을 때 WAL 을 지우므로 재생 시작 전에 다시 만들어 둔다.
		// 안 그러면 재생 중 새 파일 fsync 가 원본에 없는 node Write·f2fs Checkpoint 를 만든다
		if f.flags&dbFlagReal != 0 {
			sp := dbSpecs[fmt.Sprint(r.file)]
			c.spec = sp
			c.tables = prepTables(d, sp, c.rng)
			c.ratio = max(sp.FramesPerOp, 0.2)
			c.txOps = max(sp.OpsPerCommit, 1)
			if f.flags&dbFlagRollback == 0 {
				c.pad, err = d.Prepare(`UPDATE ` + padTable + ` SET v = ? WHERE id = ?`)
				must(err)
				c.padRows = int64(f.size / 4096)
			}
		}
		if f.flags&dbFlagRollback == 0 {
			if c.tables != nil {
				must(c.padUpdate(walPrefill))
			} else {
				must(c.update(walPrefill, walPrefill))
			}
			_, err = d.Exec("PRAGMA wal_checkpoint(PASSIVE)")
			must(err)
			if fd := c.walFd(); fd >= 0 {
				must(unix.Fsync(fd))
			}
		}
		s.conns[r.file] = c
		dirty = true
		go func(c *dbConn) {
			for x := range c.q {
				if err := c.exec(x); err != nil {
					s.e.Add(1)
					errMu.Lock()
					errKinds["SQL: "+err.Error()]++
					errMu.Unlock()
				}
				s.n.Add(1)
				if s.left.Add(-1) == 0 {
					select {
					case s.done <- struct{}{}:
					default:
					}
				}
			}
		}(c)
	}
	if dirty { // 만든 WAL 의 디렉터리 항목까지 내려 둔다
		if dfd, err := unix.Open(filepath.Join(root, "f"), unix.O_RDONLY|unix.O_DIRECTORY, 0); err == nil {
			unix.Fsync(dfd)
			unix.Close(dfd)
		}
		unix.Sync()
		// 준비 Write 를 재생과 떼어 둔다. compare.py 가 t=0 을 ±10초 안에서 Write 모양으로 맞추므로 그보다 길게 쉰다
		time.Sleep(sqlSettle)
	}
	return s
}

// 가중치 TC 는 DB 를 재생 시작 전에 한꺼번에 열고 채운다. 1~2시간 뒤에 도는 함수의 DB page 는 그사이 page cache 에서 밀려나
// 함수 첫 몇 초에 DB 본체·WAL Read 가 원본보다 수 MB 많아졌다(원본 앱은 DB 를 쓰던 중이라 cache 에 있다).
// 그래서 DB 를 warmGap 넘게 안 쓰다가 다시 쓰기 warmLead 전에 파일을 한 번 읽어 둔다. 함수 사이 쉬는 구간(20초)에 들어가 비교 구간 밖이다
const (
	warmGap  = 60 * time.Second
	warmLead = 10 * time.Second
)

func (s *sqlEngine) warm(t0 time.Time, reqs []req) {
	type pt struct {
		at   time.Duration
		file uint32
	}
	// 읽는 시각은 그 DB 를 쓰는 함수의 시작 표시(opMark) warmLead 전. 함수 안 첫 SQL 기준이면 비교 구간 안에 들어갈 수 있다
	var pts []pt
	last := map[uint32]time.Duration{}
	mark, seg := time.Duration(-1), -1
	warmed := map[uint32]int{}
	for _, r := range reqs {
		t := time.Duration(r.t) * time.Microsecond
		if r.op == opMark {
			mark, seg = t, int(r.file)
			continue
		}
		if r.op != opSQL {
			continue
		}
		l, ok := last[r.file]
		last[r.file] = t
		if mark < warmGap || ok && t-l < warmGap || warmed[r.file] == seg+1 {
			continue
		}
		warmed[r.file] = seg + 1
		pts = append(pts, pt{mark - warmLead, r.file})
	}
	sort.Slice(pts, func(i, j int) bool { return pts[i].at < pts[j].at })
	if len(pts) == 0 {
		return
	}
	go func() {
		b := make([]byte, 1<<20)
		for _, x := range pts {
			time.Sleep(time.Until(t0.Add(x.at)))
			c := s.conns[x.file]
			for _, e := range []string{"", "-wal"} {
				fd, err := unix.Open(c.path+e, unix.O_RDONLY, 0)
				if err != nil {
					continue
				}
				for off := int64(0); ; off += int64(len(b)) {
					if n, err := unix.Pread(fd, b, off); n <= 0 || err != nil {
						break
					}
				}
				unix.Close(fd)
			}
			sqlWarms.Add(1)
		}
	}()
}

func (s *sqlEngine) submit(r req) {
	s.left.Add(1)
	s.conns[r.file].q <- r
}

func (s *sqlEngine) wait() {
	for s.left.Load() > 0 {
		<-s.done
	}
	// 연결을 닫지 않는다. 마지막 연결을 닫으면 SQLite 가 WAL 전체를 DB 본체로 옮기고 WAL 을 지워서
	// 원본에 없는 Write 가 재생 끝에 생긴다. 앱 DB 는 프로세스가 사는 동안 열려 있다. 프로세스가 끝나면 커널이 fd 를 닫는다
	for _, c := range s.conns {
		close(c.q)
	}
}

// uxwl dbinfo <복사본>: 구조·설정·행 수만 출력한다. 행 내용은 읽지 않는다
func dbinfo(path string) {
	d, err := sql.Open("sqlite", "file:"+path)
	must(err)
	defer d.Close()
	d.SetMaxOpenConns(1)
	out := map[string]any{}
	for _, p := range []string{"page_size", "page_count", "freelist_count", "journal_mode", "auto_vacuum", "user_version", "encoding"} {
		var v any
		if err := d.QueryRow("PRAGMA " + p).Scan(&v); err == nil {
			if b, ok := v.([]byte); ok {
				v = string(b)
			}
			out[p] = v
		}
	}
	type tbl struct {
		Type string `json:"type"`
		Name string `json:"name"`
		SQL  string `json:"sql"`
		Rows *int64 `json:"rows,omitempty"`
	}
	var ts []tbl
	rows, err := d.Query("SELECT type, name, coalesce(sql,'') FROM sqlite_master ORDER BY type DESC, name")
	if err != nil {
		out["error"] = err.Error()
	} else {
		for rows.Next() {
			var t tbl
			if rows.Scan(&t.Type, &t.Name, &t.SQL) == nil {
				ts = append(ts, t)
			}
		}
		rows.Close()
	}
	for i := range ts {
		if ts[i].Type != "table" || strings.HasPrefix(ts[i].Name, "sqlite_") {
			continue
		}
		var n int64
		if d.QueryRow(`SELECT count(*) FROM "`+strings.ReplaceAll(ts[i].Name, `"`, `""`)+`"`).Scan(&n) == nil {
			ts[i].Rows = &n
		}
	}
	out["objects"] = ts
	js, _ := json.MarshalIndent(out, "", " ")
	fmt.Println(string(js))
}

// ---------------- 실제 테이블 ----------------
// 앱 DB 와 같은 CREATE 문으로 만들고 가짜 값으로 채운 뒤, dbwatch 로 잰 테이블별 INSERT·UPDATE·DELETE 비율대로 SQL 을 낸다.

const dbFlagReal = 8

type specTable struct {
	Name     string `json:"name"`
	Rows     int64  `json:"rows"`
	AvgBytes int64  `json:"avgRowBytes"`
	Insert   int64  `json:"insert"`
	Update   int64  `json:"update"`
	Delete   int64  `json:"delete"`
}

type dbSpec struct {
	Create       []string    `json:"create"`
	Tables       []specTable `json:"tables"`
	FramesPerOp  float64     `json:"framesPerOp"`
	OpsPerCommit int         `json:"opsPerCommit"`
}

var dbSpecs = map[string]*dbSpec{} // 파일 번호 → 구조

func specPath(root string) string { return filepath.Join(root, "dbspec.json") }

func loadSpecs(root string) {
	if b, err := os.ReadFile(specPath(root)); err == nil {
		must(json.Unmarshal(b, &dbSpecs))
	}
}

type realCol struct {
	name, kind string
	skip       bool
}

type realTbl struct {
	specTable
	q      string
	cols   []realCol
	ins    *sql.Stmt
	updCol string
	varN   int
	weight int64
	fail   int
}

func columns(d *sql.DB, t *realTbl) {
	rs, err := d.Query(`PRAGMA table_info("` + strings.ReplaceAll(t.Name, `"`, `""`) + `")`)
	if err != nil {
		return
	}
	defer rs.Close()
	var pkN int
	for rs.Next() {
		var cid, nn, pk int
		var name, typ string
		var dflt any
		if rs.Scan(&cid, &name, &typ, &nn, &dflt, &pk) != nil {
			continue
		}
		u := strings.ToUpper(typ)
		k := "T"
		switch {
		case strings.Contains(u, "INT"):
			k = "I"
		case strings.Contains(u, "REAL"), strings.Contains(u, "FLOA"), strings.Contains(u, "DOUB"):
			k = "R"
		case strings.Contains(u, "BLOB"):
			k = "B"
		}
		c := realCol{name: name, kind: k, skip: pk == 1 && u == "INTEGER"} // rowid 로 채워지는 것은 INTEGER PRIMARY KEY 뿐이다
		if pk > 0 {
			pkN++
		}
		if k == "T" || k == "B" {
			t.varN++
			if pk == 0 {
				t.updCol = name
			}
		} else if pk == 0 && t.updCol == "" {
			t.updCol = name
		}
		t.cols = append(t.cols, c)
	}
	if pkN > 1 { // 복합 키의 정수 column 은 값을 넣어야 한다
		for i := range t.cols {
			t.cols[i].skip = false
		}
	}
}

func (t *realTbl) values(rng *rand.Rand) []any {
	n := t.AvgBytes
	for _, c := range t.cols {
		if c.kind == "I" || c.kind == "R" {
			n -= 8
		}
	}
	each := int64(8)
	if t.varN > 0 && n/int64(t.varN) > each {
		each = n / int64(t.varN)
	}
	var out []any
	for _, c := range t.cols {
		if c.skip {
			continue
		}
		switch c.kind {
		case "I":
			out = append(out, rng.Int63())
		case "R":
			out = append(out, rng.Float64())
		case "B":
			b := make([]byte, each)
			rng.Read(b)
			out = append(out, b)
		default:
			b := make([]byte, each/2+1)
			rng.Read(b)
			out = append(out, fmt.Sprintf("%x", b))
		}
	}
	return out
}

func prepTables(d *sql.DB, s *dbSpec, rng *rand.Rand) []*realTbl {
	var out []*realTbl
	for _, st := range s.Tables {
		t := &realTbl{specTable: st, q: `"` + strings.ReplaceAll(st.Name, `"`, `""`) + `"`}
		columns(d, t)
		var names, marks []string
		for _, c := range t.cols {
			if !c.skip {
				names = append(names, `"`+c.name+`"`)
				marks = append(marks, "?")
			}
		}
		if len(names) == 0 {
			continue
		}
		var err error
		t.ins, err = d.Prepare("INSERT OR REPLACE INTO " + t.q + "(" + strings.Join(names, ",") + ") VALUES(" + strings.Join(marks, ",") + ")")
		if err != nil {
			continue
		}
		t.weight = st.Insert + st.Update + st.Delete
		out = append(out, t)
	}
	// 잰 동작이 있는 테이블을 하나도 못 만들었으면 (앱 전용 구조) 있는 테이블에 INSERT 한다
	var tot int64
	for _, t := range out {
		tot += t.weight
	}
	if tot == 0 {
		for _, t := range out {
			t.weight, t.Insert = 1, 1
		}
	}
	return out
}

// 구조대로 만들고 실제 행 수만큼 가짜 값을 넣는다
func prepRealDB(path string, s *dbSpec, rollback bool, padRows uint64) {
	for _, e := range []string{"", "-wal", "-shm", "-journal"} {
		os.Remove(path + e)
	}
	d, err := openDB(path, rollback)
	must(err)
	defer d.Close()
	for _, c := range s.Create {
		if _, err := d.Exec(c); err != nil {
			errMu.Lock()
			errKinds["SQL 구조: "+err.Error()]++
			errMu.Unlock()
		}
	}
	rng := rand.New(rand.NewSource(11))
	ts := prepTables(d, s, rng)
	tx, err := d.Begin()
	must(err)
	for _, t := range ts {
		st := tx.Stmt(t.ins)
		for i := int64(0); i < t.Rows; i++ {
			st.Exec(t.values(rng)...)
		}
		t.ins.Close()
	}
	must(tx.Commit())
	if !rollback { // 채움 테이블: 실제 테이블로 양을 못 채울 때만 쓴다. 한 행이 page 하나
		_, err = d.Exec("CREATE TABLE " + padTable + "(id INTEGER PRIMARY KEY, v BLOB NOT NULL)")
		must(err)
		tx, err = d.Begin()
		must(err)
		st, err := tx.Prepare("INSERT INTO " + padTable + "(id, v) VALUES(?, ?)")
		must(err)
		for i := uint64(0); i < padRows; i++ {
			_, err = st.Exec(int64(i), rowData)
			must(err)
		}
		st.Close()
		must(tx.Commit())
	}
	if !rollback {
		_, err = d.Exec("PRAGMA wal_checkpoint(TRUNCATE)")
		must(err)
	}
}

// 앱 전용 CHECK 는 ignore_check_constraints 로 끄지만, 다른 제약으로 모든 테이블이 빠지면 이 값을 돌려준다
var errNoTable = errors.New("SQL: 쓸 수 있는 테이블 없음")

// 행 동작 n 번을 transaction 하나로. 테이블은 잰 비율대로, 동작도 그 테이블의 비율대로 고른다
func (c *dbConn) realOps(n int) error {
	var tot int64
	for _, t := range c.tables {
		tot += t.weight
	}
	if tot == 0 {
		return errNoTable
	}
	tx, err := c.d.Begin()
	if err != nil {
		return err
	}
	for i := 0; i < n && tot > 0; i++ {
		u := c.rng.Int63n(tot)
		var t *realTbl
		for _, x := range c.tables {
			if u -= x.weight; u < 0 {
				t = x
				break
			}
		}
		if t == nil {
			continue
		}
		o := c.rng.Int63n(t.weight)
		switch {
		case o < t.Insert:
			_, err = tx.Stmt(t.ins).Exec(t.values(c.rng)...)
		case o < t.Insert+t.Update && t.updCol != "":
			v := make([]byte, t.AvgBytes/int64(max(1, len(t.cols)))/2+4)
			c.rng.Read(v)
			_, err = tx.Exec(`UPDATE `+t.q+` SET "`+t.updCol+`" = ? WHERE rowid = (SELECT rowid FROM `+t.q+` WHERE rowid >= ? LIMIT 1)`, fmt.Sprintf("%x", v), c.rng.Int63n(max(1, t.Rows)))
		default: // 오래된 행부터
			var res sql.Result
			res, err = tx.Exec(`DELETE FROM ` + t.q + ` WHERE rowid = (SELECT min(rowid) FROM ` + t.q + `)`)
			if err == nil { // 테이블이 비었으면 다시 채운다. 안 그러면 뒤의 transaction 이 Write 를 내지 못한다
				if k, _ := res.RowsAffected(); k == 0 {
					_, err = tx.Stmt(t.ins).Exec(t.values(c.rng)...)
				}
			}
		}
		if err != nil {
			errMu.Lock()
			errKinds["SQL 행: "+err.Error()]++
			errMu.Unlock()
			err = nil
			// 앱 전용 제약(CHECK 등)에 가짜 값이 계속 걸리는 테이블은 빼고 나머지 비율대로 쓴다
			if t.fail++; t.fail == 3 {
				tot -= t.weight
				t.weight = 0
			}
		}
	}
	return tx.Commit()
}
