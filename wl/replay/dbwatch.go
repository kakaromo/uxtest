package main

// uxwl dbwatch: 시나리오가 도는 동안 앱 DB 가 어떻게 쓰이는지 잰다. 측정 trace 와 따로 돌린다.
//
//	uxwl dbwatch --sec 120 --tc /dev/uxdb/out.json 이름=DB경로 ...
//
// - 앞뒤로 DB·WAL 을 /dev 로 복사해 행을 hash 로 비교한다 → 테이블별 INSERT·UPDATE·DELETE 수, 평균 행 크기
// - WAL frame 을 짧은 간격으로 읽는다 → commit 시각, commit 마다 바뀐 page → 어느 테이블·index 인지
// 행 내용과 hash 는 메모리에만 있고 밖으로 내보내지 않는다. /data 에는 쓰지 않는다.

import (
	"database/sql"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"hash/fnv"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

type tableSnap struct {
	byRowid map[int64]uint64
	byHash  map[uint64]int
	rows    int64
	bytes   int64
}

func copyFile(src, dst string) bool {
	in, err := os.Open(src)
	if err != nil {
		return false
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return false
	}
	defer out.Close()
	_, err = io.Copy(out, in)
	return err == nil
}

// DB 복사본을 열고 돌려준다
func openCopy(path, tmp string) (*sql.DB, error) {
	for _, e := range []string{"", "-wal", "-shm", "-journal"} {
		os.Remove(tmp + e)
	}
	if !copyFile(path, tmp) {
		return nil, fmt.Errorf("복사 실패")
	}
	copyFile(path+"-wal", tmp+"-wal")
	d, err := sql.Open("sqlite", "file:"+tmp)
	if err != nil {
		return nil, err
	}
	d.SetMaxOpenConns(1)
	return d, d.Ping()
}

func hashRow(vals []any) (uint64, int64) {
	h := fnv.New64a()
	var n int64
	var num [8]byte
	for _, v := range vals {
		switch x := v.(type) {
		case nil:
			h.Write([]byte{0})
		case int64:
			binary.LittleEndian.PutUint64(num[:], uint64(x))
			h.Write(num[:])
			n += 8
		case float64:
			fmt.Fprintf(h, "%v", x)
			n += 8
		case []byte:
			h.Write(x)
			n += int64(len(x))
		case string:
			io.WriteString(h, x)
			n += int64(len(x))
		case time.Time:
			fmt.Fprint(h, x.UnixNano())
			n += 8
		}
		h.Write([]byte{0xff})
	}
	return h.Sum64(), n
}

func snapTables(d *sql.DB) (map[string]*tableSnap, []string) {
	out := map[string]*tableSnap{}
	var names, errs []string
	rs, err := d.Query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
	if err != nil {
		return out, []string{err.Error()}
	}
	for rs.Next() {
		var n string
		if rs.Scan(&n) == nil {
			names = append(names, n)
		}
	}
	rs.Close()
	for _, n := range names {
		q := `"` + strings.ReplaceAll(n, `"`, `""`) + `"`
		s := &tableSnap{byRowid: map[int64]uint64{}, byHash: map[uint64]int{}}
		rows, err := d.Query("SELECT rowid, * FROM " + q)
		hasRowid := err == nil
		if !hasRowid {
			if rows, err = d.Query("SELECT * FROM " + q); err != nil {
				errs = append(errs, n)
				continue
			}
		}
		cols, _ := rows.Columns()
		vals := make([]any, len(cols))
		ptr := make([]any, len(cols))
		for i := range vals {
			ptr[i] = &vals[i]
		}
		for rows.Next() {
			if rows.Scan(ptr...) != nil {
				continue
			}
			s.rows++
			if hasRowid {
				h, b := hashRow(vals[1:])
				s.bytes += b
				id, _ := vals[0].(int64)
				s.byRowid[id] = h
			} else {
				h, b := hashRow(vals)
				s.bytes += b
				s.byHash[h]++
			}
		}
		rows.Close()
		out[n] = s
	}
	return out, errs
}

type tableDiff struct {
	Rows     int64 `json:"rows"`
	AvgBytes int64 `json:"avgRowBytes"`
	Insert   int64 `json:"insert"`
	Update   int64 `json:"update"`
	Delete   int64 `json:"delete"`
}

func diffTables(a, b map[string]*tableSnap) map[string]tableDiff {
	out := map[string]tableDiff{}
	for n, y := range b {
		x := a[n]
		if x == nil {
			x = &tableSnap{byRowid: map[int64]uint64{}, byHash: map[uint64]int{}}
		}
		var t tableDiff
		t.Rows = y.rows
		if y.rows > 0 {
			t.AvgBytes = y.bytes / y.rows
		}
		for id, h := range y.byRowid {
			if o, ok := x.byRowid[id]; !ok {
				t.Insert++
			} else if o != h {
				t.Update++
			}
		}
		for id := range x.byRowid {
			if _, ok := y.byRowid[id]; !ok {
				t.Delete++
			}
		}
		// WITHOUT ROWID: 행을 구별할 키가 없어 UPDATE 는 DELETE + INSERT 로 잡힌다
		for h, c := range y.byHash {
			if d := c - x.byHash[h]; d > 0 {
				t.Insert += int64(d)
			}
		}
		for h, c := range x.byHash {
			if d := c - y.byHash[h]; d > 0 {
				t.Delete += int64(d)
			}
		}
		out[n] = t
	}
	for n, x := range a {
		if _, ok := b[n]; !ok {
			out[n] = tableDiff{Delete: x.rows}
		}
	}
	return out
}

type walCommit struct {
	T     float64 `json:"t"`
	Pages int     `json:"pages"`
	pgs   []uint32
}

// WAL 을 처음부터 따라가며 commit 을 모은다. 체크섬 대신 header 의 salt 로 현재 세대의 frame 만 읽는다
type walWatch struct {
	path          string
	off           int64
	salt          [8]byte
	pageSize      int64
	cur           []uint32
	commits       []walCommit
	resets        int
	unsynced      int
	overrunFrames int
}

func (w *walWatch) poll(t float64) {
	f, err := os.Open(w.path)
	if err != nil {
		return
	}
	defer f.Close()
	h := make([]byte, 32)
	if _, err = io.ReadFull(f, h); err != nil {
		return
	}
	ps := int64(binary.BigEndian.Uint32(h[8:]))
	if ps == 0 {
		return
	}
	if string(h[16:24]) != string(w.salt[:]) { // WAL 이 처음부터 다시 쓰이기 시작함 = 앞 내용이 checkpoint 됨
		if w.pageSize != 0 {
			w.resets++
		}
		copy(w.salt[:], h[16:24])
		w.off, w.pageSize, w.cur = 32, ps, nil
	}
	frame := make([]byte, 24)
	skip := w.pageSize
	for {
		if _, err = f.ReadAt(frame, w.off); err != nil {
			return
		}
		if string(frame[8:16]) != string(w.salt[:]) {
			return
		}
		w.cur = append(w.cur, binary.BigEndian.Uint32(frame[0:]))
		w.off += 24 + skip
		if binary.BigEndian.Uint32(frame[4:]) != 0 {
			w.commits = append(w.commits, walCommit{T: t, Pages: len(w.cur), pgs: w.cur})
			w.cur = nil
		}
	}
}

func exists(p string) bool {
	_, err := os.Stat(p)
	return err == nil
}

func pct(a []int, p float64) int {
	if len(a) == 0 {
		return 0
	}
	return a[min(len(a)-1, int(p*float64(len(a))))]
}

func dbwatch(dur float64, outPath string, targets []string) {
	tmp := filepath.Dir(outPath)
	must(os.MkdirAll(tmp, 0o755))
	type job struct {
		name, path string
		before     map[string]*tableSnap
		errs       []string
		w          *walWatch
	}
	var jobs []*job
	for _, tg := range targets {
		n, p, ok := strings.Cut(tg, "=")
		if !ok {
			fatal("이름=경로 로 주세요: %s", tg)
		}
		j := &job{name: n, path: p, w: &walWatch{path: p + "-wal"}}
		d, err := openCopy(p, filepath.Join(tmp, "snap.db"))
		if err != nil {
			fmt.Fprintf(os.Stderr, "%s: %v\n", n, err)
			continue
		}
		j.before, j.errs = snapTables(d)
		d.Close()
		j.w.poll(0)
		j.w.commits, j.w.resets, j.w.cur = nil, 0, nil // 시작 전 내용은 빼고 지금부터
		jobs = append(jobs, j)
	}
	fmt.Printf("dbwatch: 시작 DB %d개, %.0f초\n", len(jobs), dur)
	t0 := time.Now()
	var wg sync.WaitGroup
	for _, j := range jobs {
		wg.Add(1)
		go func(w *walWatch) {
			defer wg.Done()
			for time.Since(t0).Seconds() < dur && !exists(outPath+".stop") {
				w.poll(time.Since(t0).Seconds())
				time.Sleep(50 * time.Millisecond)
			}
			w.poll(time.Since(t0).Seconds())
		}(j.w)
	}
	wg.Wait()

	result := map[string]any{}
	for _, j := range jobs {
		r := map[string]any{"snapshotErrors": j.errs}
		d, err := openCopy(j.path, filepath.Join(tmp, "snap.db"))
		if err != nil {
			r["error"] = err.Error()
			result[j.name] = r
			continue
		}
		after, _ := snapTables(d)
		changed := map[string]tableDiff{}
		var rows int64
		for n, t := range diffTables(j.before, after) {
			rows += t.Rows
			if t.Insert+t.Update+t.Delete > 0 {
				changed[n] = t
			}
		}
		pageObj := map[uint32]string{}
		if rs, err := d.Query("SELECT pageno, name FROM dbstat"); err == nil {
			for rs.Next() {
				var p uint32
				var n string
				if rs.Scan(&p, &n) == nil {
					pageObj[p] = n
				}
			}
			rs.Close()
		} else {
			r["pageMapError"] = err.Error()
		}
		d.Close()
		byObj := map[string]int{}
		sizes := []int{}
		for _, c := range j.w.commits {
			sizes = append(sizes, c.Pages)
			for _, p := range c.pgs {
				n := pageObj[p]
				if n == "" {
					n = "(free or new)"
				}
				byObj[n]++
			}
		}
		sort.Ints(sizes)
		total := 0
		for _, s := range sizes {
			total += s
		}
		r["tablesChanged"], r["totalRows"] = changed, rows
		r["wal"] = map[string]any{"commits": len(j.w.commits), "resets": j.w.resets, "pages": total,
			"pagesPerCommit": map[string]int{"p50": pct(sizes, 0.5), "p90": pct(sizes, 0.9), "max": pct(sizes, 1)}}
		r["pagesByObject"] = byObj
		tl := j.w.commits
		r["commitTimeline"] = tl
		result[j.name] = r
	}
	os.Remove(filepath.Join(tmp, "snap.db"))
	for _, e := range []string{"-wal", "-shm", "-journal"} {
		os.Remove(filepath.Join(tmp, "snap.db") + e)
	}
	js, _ := json.MarshalIndent(result, "", " ")
	must(os.WriteFile(outPath, js, 0o644))
	fmt.Printf("dbwatch: 끝 → %s\n", outPath)
}
