// uxwl: UX workload TC 재생기 (기기에서 실행, root)
//
//	uxwl prep  --root /data/local/tmp/uxwl tc.bin   미리 있어야 하는 파일을 만들고 채운다 (page cache 는 비우지 않는다)
//	uxwl run   --root /data/local/tmp/uxwl tc.bin   시각에 맞춰 파일 동작을 재생하고 result.json 을 쓴다
//	uxwl clean --root /data/local/tmp/uxwl          재생 디렉터리를 지운다
//
// TC 형식 (little endian, gen_tc.py 가 만든다)
//
//	header  "UXWL0002" | nfiles u32 | 0 u32 | nreq u64       ("UXWL0001" 은 파일에 dir 이 없다)
//	files   size u64 | flags u8 (1 = prefill, 2 = SQLite DB, 4 = rollback journal DB, 8 = 실제 구조 DB, 16 = 새 폴더 안 파일) | dir u32 (0 = f/ 바로 아래)
//	reqs    t_us u64 | op u8 | file u32 | off u64 | len u32
//
// op: 0 R(O_DIRECT pread) 1 W(pwrite+sync_file_range) 2 WB(pwrite) 3 WD(O_DIRECT pwrite)
//
//	4 FS(fsync) 6 UNLINK 7 TRUNC(off=새 크기) 8 MARK(file=타임라인 구간 번호)
//	9 FA(atomic commit: F2FS_IOC_COMMIT_ATOMIC_WRITE) 10 WX(atomic write 안 pwrite, 처음이면 START_ATOMIC_WRITE)
//	11 CP(디렉터리 fsync → f2fs Checkpoint) 12 TRIM(FITRIM: 지운 파일의 블록을 f2fs 가 Discard 로 반납)
//	13 DS(fsync 뒤 디렉터리 fsync: SQLite 새 journal·AtomicFile 이 하는 것. 동작은 CP 와 같고 원인이 있는 쪽)
//	14 SCREEN(file=1 켜기: 깨우고 잠금 해제, 켜 있는 동안 10초마다 깨우기 / 0 끄기)
//	15 SQL(실제 SQLite transaction. file=DB, off=page 수 | 서로 다른 page 수<<32, len=sqlite.go 의 동작)
package main

import (
	"bufio"
	"encoding/binary"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"math"
	"math/rand"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"sort"
	"sync"
	"sync/atomic"
	"time"
	"unsafe"

	"golang.org/x/sys/unix"
)

const (
	opR = iota
	opW
	opWB
	opWD
	opFS
	_
	opUnlink
	opTrunc
	opMark
	opFA
	opWX
	opCP
	opTrim
	opDS
	opScreen
	opSQL
	opSync // 시나리오 단계의 sync (예: cold start 전 "sync; drop_caches"). 앱 동작이 아니라 측정 절차지만 원본 trace 에 들어 있다
	nOps
)

// include/uapi/linux/f2fs.h: _IO(0xf5, 1), _IO(0xf5, 2)
const (
	f2fsStartAtomic  = 0xf501
	f2fsCommitAtomic = 0xf502
)

var opName = [nOps]string{"R", "W", "WB", "WD", "FS", "", "UNLINK", "TRUNC", "MARK", "FA", "WX", "CP", "TRIM", "DS", "SCREEN", "SQL", "SYNC"}

type req struct {
	t    uint64
	op   uint8
	file uint32
	off  uint64
	ln   uint32
}

type tcFile struct {
	size    uint64
	prefill bool
	flags   uint8
	dir     uint32 // 원본 상위 폴더 (f/g<번호>/). 0 = f/ 바로 아래
}

func load(path string) ([]tcFile, []req) {
	f, err := os.Open(path)
	must(err)
	defer f.Close()
	r := bufio.NewReaderSize(f, 1<<20)
	var magic [8]byte
	_, err = io.ReadFull(r, magic[:])
	must(err)
	rec := 9
	switch string(magic[:]) {
	case "UXWL0001":
	case "UXWL0002":
		rec = 13
	default:
		fatal("TC 형식이 아니에요: %s", path)
	}
	var nf, pad uint32
	var nr uint64
	must(binary.Read(r, binary.LittleEndian, &nf))
	must(binary.Read(r, binary.LittleEndian, &pad))
	must(binary.Read(r, binary.LittleEndian, &nr))
	files := make([]tcFile, nf)
	b := make([]byte, 25)
	for i := range files {
		_, err = io.ReadFull(r, b[:rec])
		must(err)
		files[i] = tcFile{binary.LittleEndian.Uint64(b), b[8]&1 != 0, b[8], 0}
		if rec == 13 {
			files[i].dir = binary.LittleEndian.Uint32(b[9:])
		}
	}
	fileFlags = make([]uint8, nf)
	fileDirs = make([]uint32, nf)
	for i, f := range files {
		fileFlags[i] = f.flags
		fileDirs[i] = f.dir
	}
	reqs := make([]req, nr)
	for i := range reqs {
		_, err = io.ReadFull(r, b)
		must(err)
		reqs[i] = req{binary.LittleEndian.Uint64(b), b[8], binary.LittleEndian.Uint32(b[9:]),
			binary.LittleEndian.Uint64(b[13:]), binary.LittleEndian.Uint32(b[21:])}
	}
	return files, reqs
}

// O_DIRECT 용 정렬 버퍼
func aligned(n int) []byte {
	b, err := unix.Mmap(-1, 0, n, unix.PROT_READ|unix.PROT_WRITE, unix.MAP_ANON|unix.MAP_PRIVATE)
	must(err)
	return b
}

const maxIO = 16 << 20

// 동시에 내는 O_DIRECT Write 수. 이 커널(6.12, mode=adaptive)은 새 block 을 할당하는 direct pwrite 둘이 겹치면
// 파일끼리 block 을 하나씩 번갈아 할당해 Write 가 4KB 로 쪼개진다(파일 5개 동시 16MB → extent 1000개 넘게).
// 원본 카메라 앱은 스레드 3개가 써도 2MB 마다 extent 하나라, 하나씩 내야 원본 배치가 나온다(하나씩이 오히려 빠르다).
// AIO 는 도움이 안 된다: 할당하는 direct Write 는 io_submit 안에서 끝까지 기다린다
var maxWD = 1

var wbuf []byte // Write 내용 (난수, 읽기 전용으로 공유)

var (
	errMu    sync.Mutex
	errKinds = map[string]int{}
)

func isExcl(op uint8) bool {
	return op == opFS || op == opUnlink || op == opTrunc || op == opFA || op == opWX || op == opWD
}

// 새 폴더 안 파일 (flags 16): 원본 앱은 폴더를 새로 만들고 그 안에 파일을 써서 fsync 했다. 아직 Checkpoint 되지 않은
// 폴더 안 파일의 fsync 는 f2fs 가 Checkpoint 로 처리한다 (cp_reason "node needs cp"). 폴더는 파일을 처음 만들 때 만든다
const flagNewDir = 16

var fileFlags []uint8 // load 가 채운다

// 원본 폴더 구조: 원본에서 같은 폴더에 있던 파일은 TC 에서도 같은 폴더(f/g<번호>/)에 둔다. 앱은 파일을 수백 개 폴더에 나눠 두므로
// 파일을 만들고 지울 때 dirty 가 되는 폴더 inode·dentry page 가 많고, Checkpoint 가 그만큼 더 쓴다. 폴더 하나에 모으면 그 몫이 빠진다
var fileDirs []uint32

func dirPath(root string, d uint32) string { return filepath.Join(root, "f", fmt.Sprintf("g%05d", d)) }

func newDir(id uint32) bool { return int(id) < len(fileFlags) && fileFlags[id]&flagNewDir != 0 }

func fpath(root string, id uint32) string {
	if newDir(id) {
		return filepath.Join(root, "f", fmt.Sprintf("d%06d", id), fmt.Sprintf("%06d", id))
	}
	if int(id) < len(fileDirs) && fileDirs[id] != 0 {
		return filepath.Join(dirPath(root, fileDirs[id]), fmt.Sprintf("%06d", id))
	}
	return filepath.Join(root, "f", fmt.Sprintf("%06d", id))
}

func prep(root string, files []tcFile) {
	must(os.MkdirAll(filepath.Join(root, "f"), 0o755))
	for _, f := range files {
		if f.dir != 0 {
			must(os.MkdirAll(dirPath(root, f.dir), 0o755)) // 원래 있던 폴더: 재생 전 Discard 대기의 sync 로 Checkpoint 된다
		}
	}
	var need, done uint64
	for _, f := range files {
		if f.prefill {
			need += f.size
		}
	}
	start := time.Now()
	for id, f := range files {
		p := fpath(root, uint32(id))
		if f.flags&dbFlagSQLite != 0 {
			if f.flags&dbFlagReal != 0 {
				prepRealDB(p, dbSpecs[fmt.Sprint(id)], f.flags&dbFlagRollback != 0, f.size/4096)
			} else {
				prepDB(p, f.size/4096, f.flags&dbFlagRollback != 0)
			}
			need += f.size
			continue
		}
		if !f.prefill {
			os.Remove(p) // 새로 만들 파일은 없는 상태로 시작
			if newDir(uint32(id)) {
				os.RemoveAll(filepath.Dir(p)) // 폴더도 없는 상태로 (남아 있으면 이미 Checkpoint 된 폴더라 원본과 달라진다)
			}
			continue
		}
		// 크기가 같아도 지우고 새로 쓴다: 앞 실행이 덮어써 블록 배치가 섞인 파일을 다시 쓰면 실행마다 Write 가 다르게 쪼개진다
		os.Remove(p)
		fd, err := unix.Open(p, unix.O_RDWR|unix.O_CREAT|unix.O_TRUNC, 0o644)
		must(err)
		for off := uint64(0); off < f.size; off += maxIO {
			n := min(f.size-off, maxIO)
			_, err = unix.Pwrite(fd, wbuf[:n], int64(off))
			must(err)
		}
		must(unix.Fsync(fd))
		unix.Close(fd)
		done += f.size
	}
	unix.Sync()
	// page cache 는 비우지 않는다: Read 는 O_DIRECT 라 상관없고, 비우면 inode·node 를 다시 읽는 4KB Read 가 생긴다
	fmt.Printf("prep: 미리 채운 파일 %d MB, %.1fs\n", need>>20, time.Since(start).Seconds())
}

// 파일별 fd 두 개(buffered, direct)와 순서 잠금. FS·UNLINK·TRUNC 는 그 파일의 진행 중 요청이 끝난 뒤에 한다
type ofile struct {
	mu       sync.RWMutex
	buf, dio int
	gone     bool
	atomic   bool // START_ATOMIC_WRITE 뒤 COMMIT 전
	// 발행 순서 (주 루프만 만진다). 잠금은 동시 실행만 막아서, 뒤에 발행한 UNLINK·fsync 가 앞 Write 보다 먼저 잠금을 잡기도 했다
	// (UNLINK 8~25% ENOENT, 뒤늦은 Write 가 O_CREAT 로 파일을 되살림)
	lastExcl chan struct{}   // 마지막 독점 동작이 끝나면 닫힘
	shared   []chan struct{} // 그 뒤 발행한 공유 동작
}

// 파일 안 발행 순서를 지키도록 먼저 끝나야 할 동작을 돌려주고 자기를 등록한다. 독점은 앞 동작 전부, 공유는 앞 독점만 기다린다
func (f *ofile) order(excl bool, done chan struct{}) []chan struct{} {
	var wait []chan struct{}
	if f.lastExcl != nil {
		wait = append(wait, f.lastExcl)
	}
	if excl {
		wait = append(wait, f.shared...)
		f.lastExcl, f.shared = done, nil
	} else {
		f.shared = append(f.shared, done)
	}
	return wait
}

type store struct {
	root string
	mu   sync.Mutex
	m    map[uint32]*ofile
}

func (s *store) get(id uint32) *ofile {
	s.mu.Lock()
	defer s.mu.Unlock()
	f := s.m[id]
	if f == nil {
		f = &ofile{buf: -1, dio: -1}
		s.m[id] = f
	}
	return f
}

// 호출자가 f.mu 를 잡고 있어야 한다
func (s *store) fd(id uint32, f *ofile, direct bool) int {
	p := &f.buf
	fl := unix.O_RDWR | unix.O_CREAT
	if direct {
		p, fl = &f.dio, fl|unix.O_DIRECT
	}
	if *p < 0 {
		fp := fpath(s.root, id)
		fd, err := unix.Open(fp, fl, 0o644)
		if err == unix.ENOENT && newDir(id) {
			unix.Mkdir(filepath.Dir(fp), 0o755)
			fd, err = unix.Open(fp, fl, 0o644)
		}
		if err != nil {
			return -1
		}
		*p = fd
	}
	return *p
}

// 지연 히스토그램: 1µs~100s 로그 칸
const nb = 160

type hist struct{ c [nb]uint64 }

func bucket(ns int64) int {
	if ns < 1000 {
		return 0
	}
	return min(nb-1, int(math.Log10(float64(ns)/1000)*20)+1)
}
func (h *hist) add(ns int64) { atomic.AddUint64(&h.c[bucket(ns)], 1) }
func (h *hist) pct(p float64) float64 {
	var n uint64
	for _, c := range h.c {
		n += c
	}
	if n == 0 {
		return 0
	}
	k := uint64(math.Ceil(p * float64(n)))
	var acc uint64
	for i, c := range h.c {
		acc += c
		if acc >= k {
			if i == 0 {
				return 0.001
			}
			return math.Pow(10, float64(i)/20) / 1000 // ms (칸 위쪽 끝)
		}
	}
	return 0
}

type stat struct {
	n, bytes, errs uint64
	lat            hist
}

type segStat struct {
	ops [nOps]stat
}

// Linux AIO (io_submit). 원본 앱은 thread 여러 개·readahead 가 같은 순간에 Read 를 내고 커널이 block plug 로 묶어
// 한꺼번에 UFS 에 보낸다 (Chrome cold start QD 50~60). pread 를 goroutine 마다 따로 부르면 수십 µs 간격으로 나가
// QD 가 7 에 머물렀다. 그래서 같은 순간의 Read 묶음은 io_submit 한 번으로 낸다 (io_submit 안에서 plug 가 걸린다).
type iocb struct {
	data     uint64
	key      uint32
	rwFlags  uint32
	opcode   uint16
	prio     int16
	fd       uint32
	buf      uint64
	nbytes   uint64
	offset   int64
	reserved uint64
	flags    uint32
	resfd    uint32
}

type ioEvent struct {
	data, obj uint64
	res, res2 int64
}

const (
	aioDepth  = 128 // 묶음 하나의 최대 Read 수
	burstGap  = 100 // µs: 앞 Read 와 이 안에 이어지면 같은 묶음
	burstSpan = 200 // µs: 묶음 첫 Read 부터 이 안까지만 (앞당겨 내는 시간 상한)
	iocbPread = 0
)

var aioCtxs = make(chan uintptr, 512)

func aioCtx() (uintptr, bool) {
	select {
	case c := <-aioCtxs:
		return c, true
	default:
	}
	var c uintptr
	if _, _, en := unix.Syscall(unix.SYS_IO_SETUP, aioDepth, uintptr(unsafe.Pointer(&c)), 0); en != 0 {
		return 0, false
	}
	return c, true
}

func aioPut(c uintptr) {
	select {
	case aioCtxs <- c:
	default:
		unix.Syscall(unix.SYS_IO_DESTROY, c, 0, 0)
	}
}

// aioOK: 기기 커널이 AIO 를 지원하는지 (CONFIG_AIO). 안 되면 묶음 없이 pread 로 낸다
func aioOK() bool {
	c, ok := aioCtx()
	if ok {
		aioPut(c)
	}
	return ok
}

func run(root string, files []tcFile, reqs []req, speed float64, maxQD int, out string) {
	s := &store{root: root, m: map[uint32]*ofile{}}
	sqlE := newSQLEngine(root, files, reqs)
	var ops [nOps]stat
	var lag hist
	var late, lateMax int64
	nseg := 1
	for _, r := range reqs {
		if r.op == opMark {
			nseg = max(nseg, int(r.file)+1)
		}
	}
	segs := make([]segStat, nseg)
	sem := make(chan struct{}, maxQD)
	wdSem := make(chan struct{}, maxWD)
	pool := sync.Pool{New: func() any { return aligned(maxIO) }}
	var wg sync.WaitGroup
	var qd, qdMax int64

	// 화면이 꺼진 구간에 기기가 suspend 되면 타이머가 멈춰 요청 시각이 밀린다 → 재생하는 동안 wakelock
	if wakelock {
		os.WriteFile("/sys/power/wake_lock", []byte("uxwl"), 0)
		defer os.WriteFile("/sys/power/wake_unlock", []byte("uxwl"), 0)
	}
	defer screen(false)
	var mono, boot unix.Timespec
	unix.ClockGettime(unix.CLOCK_MONOTONIC, &mono)
	unix.ClockGettime(unix.CLOCK_BOOTTIME, &boot)
	t0 := time.Now()
	sqlE.warm(t0, reqs)
	record := func(r req, sg *segStat, ns int64, err error) {
		for _, o := range []*stat{&ops[r.op], &sg.ops[r.op]} {
			atomic.AddUint64(&o.n, 1)
			atomic.AddUint64(&o.bytes, uint64(r.ln))
			if err != nil {
				atomic.AddUint64(&o.errs, 1)
			}
			o.lat.add(ns)
		}
		if err != nil {
			errMu.Lock()
			errKinds[opName[r.op]+": "+err.Error()]++
			errMu.Unlock()
		}
	}
	exec := func(r req, sg *segStat) {
		f := s.get(r.file)
		// WD 도 파일마다 하나씩: 앱은 파일 하나를 스레드 하나가 순서대로 쓴다. 동시에 쓰면 f2fs 가 파일끼리 블록을 섞어 할당해 Write 가 4KB 로 쪼개진다
		if isExcl(r.op) {
			f.mu.Lock()
			defer f.mu.Unlock()
		} else {
			f.mu.RLock()
			defer f.mu.RUnlock()
		}
		st := time.Now()
		var err error
		n := int(min(r.ln, maxIO))
		switch r.op {
		case opR, opWD:
			fd := s.fd(r.file, f, true)
			if fd < 0 {
				err = unix.ENOENT
				break
			}
			if r.op == opR {
				b := pool.Get().([]byte)
				_, err = unix.Pread(fd, b[:n], int64(r.off))
				pool.Put(b)
			} else {
				_, err = unix.Pwrite(fd, wbuf[:n], int64(r.off))
			}
		case opW, opWB:
			fd := s.fd(r.file, f, false)
			if fd < 0 {
				err = unix.ENOENT
				break
			}
			_, err = unix.Pwrite(fd, wbuf[:n], int64(r.off))
			if err == nil && r.op == opW {
				err = unix.SyncFileRange(fd, int64(r.off), int64(n), unix.SYNC_FILE_RANGE_WRITE)
			}
		case opFS:
			if fd := s.fd(r.file, f, false); fd >= 0 {
				err = unix.Fsync(fd)
			}
		case opTrim:
			// struct fstrim_range {start, len, minlen u64}; FITRIM = _IOWR('X', 121, 24 bytes)
			dfd, e := unix.Open(root, unix.O_RDONLY|unix.O_DIRECTORY, 0)
			if err = e; e == nil {
				rg := [3]uint64{0, math.MaxUint64, 0}
				if _, _, en := unix.Syscall(unix.SYS_IOCTL, uintptr(dfd), 0xC0185879, uintptr(unsafe.Pointer(&rg[0]))); en != 0 {
					err = en
				}
				unix.Close(dfd)
			}
		case opCP, opDS:
			dfd, e := unix.Open(filepath.Join(root, "f"), unix.O_RDONLY|unix.O_DIRECTORY, 0)
			if err = e; e == nil {
				err = unix.Fsync(dfd)
				unix.Close(dfd)
			}
		case opWX, opFA:
			fd := s.fd(r.file, f, false)
			if fd < 0 {
				err = unix.ENOENT
				break
			}
			if !f.atomic {
				if err = unix.IoctlSetInt(fd, f2fsStartAtomic, 0); err != nil {
					break
				}
				f.atomic = true
			}
			if r.op == opWX {
				_, err = unix.Pwrite(fd, wbuf[:n], int64(r.off))
			} else {
				err = unix.IoctlSetInt(fd, f2fsCommitAtomic, 0)
				f.atomic = false
			}
		case opTrunc:
			if fd := s.fd(r.file, f, false); fd >= 0 {
				err = unix.Ftruncate(fd, int64(r.off))
			}
		case opUnlink:
			for _, p := range []*int{&f.buf, &f.dio} {
				if *p >= 0 {
					unix.Close(*p)
					*p = -1
				}
			}
			err = unix.Unlink(fpath(root, r.file))
			f.gone = true
		}
		record(r, sg, time.Since(st).Nanoseconds(), err)
	}
	// Read 묶음을 io_submit 한 번으로. 파일 잠금은 파일 번호 순서로 잡는다 (FS·UNLINK 와 엇갈려 멈추지 않게)
	useAIO := aioOK()
	locks := func(grp []req) ([]uint32, map[uint32]*ofile) {
		ids := make([]uint32, 0, len(grp))
		seen := map[uint32]*ofile{}
		for _, r := range grp {
			if _, ok := seen[r.file]; !ok {
				seen[r.file] = s.get(r.file)
				ids = append(ids, r.file)
			}
		}
		sort.Slice(ids, func(a, b int) bool { return ids[a] < ids[b] })
		return ids, seen
	}
	// submit: 잠금을 잡은 상태에서 io_submit 까지 하고, 완료를 기다려 기록하는 함수를 돌려준다
	submit := func(grp []req, sg *segStat, seen map[uint32]*ofile) func() {
		ctx, ok := aioCtx()
		if !ok {
			for _, r := range grp {
				st := time.Now()
				b := pool.Get().([]byte)
				var err error = unix.ENOENT
				if fd := s.fd(r.file, seen[r.file], true); fd >= 0 {
					_, err = unix.Pread(fd, b[:min(r.ln, maxIO)], int64(r.off))
				}
				pool.Put(b)
				record(r, sg, time.Since(st).Nanoseconds(), err)
			}
			return func() {}
		}
		cbs := make([]iocb, 0, len(grp))
		bufs := make([][]byte, 0, len(grp))
		idx := make([]int, 0, len(grp))
		for k, r := range grp {
			fd := s.fd(r.file, seen[r.file], true)
			if fd < 0 {
				record(r, sg, 0, unix.ENOENT)
				continue
			}
			b := pool.Get().([]byte)
			n := min(r.ln, maxIO)
			bufs = append(bufs, b)
			idx = append(idx, k)
			cbs = append(cbs, iocb{data: uint64(k), opcode: iocbPread, fd: uint32(fd),
				buf: uint64(uintptr(unsafe.Pointer(&b[0]))), nbytes: uint64(n), offset: int64(r.off)})
		}
		var ptrs []*iocb
		sub := uintptr(0)
		st := time.Now()
		if len(cbs) > 0 {
			ptrs = make([]*iocb, len(cbs))
			for k := range cbs {
				ptrs[k] = &cbs[k]
			}
			var en unix.Errno
			if sub, _, en = unix.Syscall(unix.SYS_IO_SUBMIT, ctx, uintptr(len(ptrs)), uintptr(unsafe.Pointer(&ptrs[0]))); en != 0 {
				sub = 0
			}
		}
		return func() {
			defer aioPut(ctx)
			defer func() {
				for _, b := range bufs {
					pool.Put(b)
				}
			}()
			for k := int(sub); k < len(cbs); k++ { // 못 낸 것은 pread 로
				r := grp[idx[k]]
				t1 := time.Now()
				_, err := unix.Pread(int(cbs[k].fd), bufs[k][:cbs[k].nbytes], int64(r.off))
				record(r, sg, time.Since(t1).Nanoseconds(), err)
			}
			evs := make([]ioEvent, sub)
			for got := 0; got < int(sub); {
				n, _, en := unix.Syscall6(unix.SYS_IO_GETEVENTS, ctx, 1, uintptr(int(sub)-got),
					uintptr(unsafe.Pointer(&evs[got])), 0, 0)
				if en == unix.EINTR {
					continue
				}
				if en != 0 {
					break
				}
				ns := time.Since(st).Nanoseconds()
				for _, e := range evs[got : got+int(n)] {
					var err error
					if e.res < 0 {
						err = unix.Errno(-e.res)
					}
					record(grp[e.data], sg, ns, err)
				}
				got += int(n)
			}
			runtime.KeepAlive(cbs)
			runtime.KeepAlive(ptrs)
		}
	}
	burst := func(grp []req, sg *segStat) {
		ids, seen := locks(grp)
		for _, id := range ids {
			seen[id].mu.RLock()
		}
		submit(grp, sg, seen)()
		for _, id := range ids {
			seen[id].mu.RUnlock()
		}
	}
	// Read 는 goroutine 하나가 시각 순서대로 io_submit 하고 완료만 따로 기다린다. 묶음마다 goroutine 을 띄우면
	// 준비(잠금·fd·ctx)에 0.5ms 쯤 걸려 뒤 Read 가 먼저 나가, 원본의 이어 읽기가 Sequential 로 안 보였다.
	// 주 루프에서 바로 io_submit 하면 그동안 다음 요청이 늦어진다 (늦음 1.3%).
	// 원본 readahead 체인의 QD(50+)는 못 맞춘다: 128KB io_submit 이 80µs 라 35µs 간격을 못 따라가고, readahead(2) 로 맡기면 크기·양이 어긋났다
	type rjob struct {
		grp []req
		sg  *segStat
		fin func()
	}
	rq := make(chan rjob, 1024)
	if useAIO {
		go func() {
			for j := range rq {
				ids, seen := locks(j.grp)
				held := 0
				for _, id := range ids {
					if !seen[id].mu.TryRLock() {
						break
					}
					held++
				}
				if held < len(ids) { // FS·UNLINK 가 잡고 있으면 이 묶음만 따로 기다린다
					for _, id := range ids[:held] {
						seen[id].mu.RUnlock()
					}
					go func(j rjob) { burst(j.grp, j.sg); j.fin() }(j)
					continue
				}
				wait := submit(j.grp, j.sg, seen)
				go func(j rjob) {
					wait()
					for _, id := range ids {
						seen[id].mu.RUnlock()
					}
					j.fin()
				}(j)
			}
		}()
		defer close(rq)
	}
	// 같은 파일·같은 동작(R/W/WD)이 0.2ms 안에 이어지면 한 goroutine 이 순서대로 낸다.
	// 따로 띄우면 장치에 닿는 순서가 섞여 readahead·카메라 저장 같은 Sequential 요청이 Random 처럼 보이고 QD 가 부풀었다
	seg := 0
	for i := 0; i < len(reqs); {
		r := reqs[i]
		due := time.Duration(float64(r.t) * 1000 / speed)
		if d := due - time.Since(t0); d > 0 {
			if d > 2*time.Millisecond {
				time.Sleep(d - time.Millisecond)
			}
			for time.Since(t0) < due {
			}
		}
		if r.op == opMark {
			seg = int(r.file)
			i++
			continue
		}
		if r.op == opScreen {
			screen(r.file == 1)
			i++
			continue
		}
		if r.op == opSync { // 다른 동작을 막지 않게 따로 부른다 (원본도 sh 가 따로 불렀다)
			go unix.Sync()
			atomic.AddUint64(&ops[opSync].n, 1)
			atomic.AddUint64(&segs[seg].ops[opSync].n, 1)
			i++
			continue
		}
		if r.op == opSQL {
			lg := int64(time.Since(t0) - due)
			lag.add(lg)
			lateMax = max(lateMax, lg)
			sqlE.submit(r)
			atomic.AddUint64(&ops[opSQL].n, 1)
			atomic.AddUint64(&segs[seg].ops[opSQL].n, 1)
			i++
			continue
		}
		j := i + 1
		if r.op == opR && useAIO {
			// 같은 파일에서 앞 Read 에 붙은 Read 가 오면 묶음을 끊는다. io_submit 한 번은 plug 하나라 커널이
			// 붙은 Read 를 합쳐, 원본의 128KB readahead 열 개가 512KB 몇 개가 됐다 (Sequential·size·QD 가 어긋남)
			ends := map[[2]uint64]bool{{uint64(r.file), r.off + uint64(r.ln)}: true}
			for j < len(reqs) && j-i < aioDepth && reqs[j].op == opR && reqs[j].t-reqs[j-1].t <= burstGap && reqs[j].t-r.t <= burstSpan &&
				!ends[[2]uint64{uint64(reqs[j].file), reqs[j].off}] {
				ends[[2]uint64{uint64(reqs[j].file), reqs[j].off + uint64(reqs[j].ln)}] = true
				j++
			}
		}
		if r.op == opR && useAIO { // Read (묶음) → 순서대로 io_submit
			lg := int64(time.Since(t0) - due)
			lag.add(lg)
			if lg > int64(5*time.Millisecond) {
				late++
			}
			lateMax = max(lateMax, lg)
			sem <- struct{}{}
			wg.Add(1)
			q := atomic.AddInt64(&qd, 1)
			if q > atomic.LoadInt64(&qdMax) {
				atomic.StoreInt64(&qdMax, q)
			}
			// Read 는 앞 동작을 기다리지 않고(제출 순서·QD 유지), 뒤 독점 동작만 이 Read 를 기다린다
			done := make(chan struct{})
			seenF := map[uint32]bool{}
			for _, x := range reqs[i:j] {
				if !seenF[x.file] {
					seenF[x.file] = true
					f := s.get(x.file)
					f.shared = append(f.shared, done)
				}
			}
			rq <- rjob{reqs[i:j], &segs[seg], func() { close(done); atomic.AddInt64(&qd, -1); <-sem; wg.Done() }}
			i = j
			continue
		}
		if r.op == opR && !useAIO || r.op == opW || r.op == opWD { // AIO 면 붙은 Read 도 따로 띄워 원본처럼 QD 가 쌓이게
			for j < len(reqs) && reqs[j].file == r.file && reqs[j].op == r.op && (reqs[j].t-r.t <= 200 || r.op == opWD && reqs[j].t-reqs[j-1].t <= 200) {
				j++
			}
		}
		// fsync 바로 뒤 디렉터리 fsync(DS) 는 fsync 가 끝난 뒤에 (SQLite 순서). 따로 띄우면 DS 의 Checkpoint 가
		// 먼저 끝나 파일 node 까지 써 버리고, fsync 는 쓸 것이 없어 앱 스레드 node Write 가 사라졌다
		if (r.op == opFS || r.op == opFA) && j < len(reqs) && reqs[j].op == opDS && reqs[j].t-r.t <= 1000 {
			j++
		}
		lg := int64(time.Since(t0) - due)
		lag.add(lg)
		if lg > int64(5*time.Millisecond) {
			late++
		}
		lateMax = max(lateMax, lg)
		sem <- struct{}{}
		wg.Add(1)
		q := atomic.AddInt64(&qd, 1)
		if q > atomic.LoadInt64(&qdMax) {
			atomic.StoreInt64(&qdMax, q)
		}
		done := make(chan struct{})
		var before []chan struct{}
		if r.op != opCP && r.op != opDS && r.op != opTrim { // 파일에 묶이지 않는 동작 빼고. 한 묶음은 파일 하나
			before = s.get(r.file).order(isExcl(r.op), done)
		}
		go func(grp []req, sg *segStat) {
			defer func() { close(done); atomic.AddInt64(&qd, -1); <-sem; wg.Done() }()
			for _, c := range before { // wdSem·파일 잠금을 잡기 전에 기다린다 (앞 동작이 그것을 기다리면 멈춘다)
				<-c
			}
			if grp[0].op == opWD {
				wdSem <- struct{}{}
				defer func() { <-wdSem }()
			}
			for k := 0; k < len(grp); k++ {
				r := grp[k]
				// 이어지는 WD 는 pwrite 하나로: 원본 앱의 큰 pwrite 가 커널에서 512KB 씩 나뉜 것이다.
				// 조각마다 따로 쓰면 다른 파일 Write 와 블록이 섞여 할당돼 4KB 로 쪼개진다
				for r.op == opWD && k+1 < len(grp) && grp[k+1].off == r.off+uint64(r.ln) && r.ln+grp[k+1].ln <= maxIO {
					k++
					r.ln += grp[k].ln
				}
				exec(r, sg)
			}
		}(reqs[i:j], &segs[seg])
		i = j
	}
	wg.Wait()
	sqlE.wait()
	elapsed := time.Since(t0)

	sum := func(a *[nOps]stat) map[string]any {
		m := map[string]any{}
		for i := range a {
			o := &a[i]
			if o.n == 0 {
				continue
			}
			m[opName[i]] = map[string]any{"n": o.n, "MB": float64(o.bytes) / 1e6, "errors": o.errs,
				"latMs": map[string]float64{"p50": o.lat.pct(0.5), "p99": o.lat.pct(0.99), "p999": o.lat.pct(0.999)}}
		}
		return m
	}
	ss := make([]map[string]any, len(segs))
	for i := range segs {
		ss[i] = sum(&segs[i].ops)
	}
	res := map[string]any{
		"startMonotonic": float64(mono.Sec) + float64(mono.Nsec)/1e9,
		"startBoottime":  float64(boot.Sec) + float64(boot.Nsec)/1e9,
		"elapsedSec":     elapsed.Seconds(), "scheduledSec": float64(reqs[len(reqs)-1].t) / 1e6 / speed,
		"speed": speed, "maxQD": maxQD, "qdMax": qdMax, "requests": len(reqs),
		"lateOver5ms": late, "lagMs": map[string]float64{"p50": lag.pct(0.5), "p99": lag.pct(0.99), "max": float64(lateMax) / 1e6},
		"ops": sum(&ops), "segments": ss, "errorKinds": errKinds,
		"sqlFrames": map[string]int64{"real": sqlFramesReal.Load(), "pad": sqlFramesPad.Load()},
		"sqlWarms":  sqlWarms.Load(),
	}
	b, _ := json.MarshalIndent(res, "", " ")
	must(os.WriteFile(out, b, 0o644))
	keys := []string{}
	for k := range res["ops"].(map[string]any) {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	fmt.Printf("run: %d 요청, %.1fs (예정 %.1fs), 늦음(>5ms) %d, lag p99 %.2fms, ops %v → %s\n",
		len(reqs), elapsed.Seconds(), res["scheduledSec"], late, lag.pct(0.99), keys, out)
}

var (
	wakelock  bool
	screenOn  bool
	screenStp chan struct{}
)

func sh(cmd string) { exec.Command("sh", "-c", cmd).Run() }

// 앱 사용 구간은 화면을 켜고(원본 앱 시나리오는 화면을 켜고 쟀다), 화면 꺼짐 구간은 끈다(대기 S 는 화면을 끄고 쟀다).
// 화면 꺼짐 시간(30초)보다 자주 키코드 0 을 보내 켜진 상태를 유지한다 (설정은 바꾸지 않는다).
// KEYCODE_WAKEUP 은 켜진 화면의 꺼짐 시간을 늘리지 않는다. 화면이 30초마다 꺼졌다 켜지고, 켜질 때마다 다른 앱의 fsync·Flush 가 나왔다
func screen(on bool) {
	if on == screenOn {
		return
	}
	screenOn = on
	if on {
		sh("input keyevent KEYCODE_WAKEUP; wm dismiss-keyguard")
		screenStp = make(chan struct{})
		go func(stop chan struct{}) {
			t := time.NewTicker(10 * time.Second)
			defer t.Stop()
			for {
				select {
				case <-stop:
					return
				case <-t.C:
					sh("input keyevent 0")
				}
			}
		}(screenStp)
	} else {
		close(screenStp)
		sh("input keyevent KEYCODE_SLEEP")
	}
}

func main() {
	if len(os.Args) < 2 {
		fatal("usage: uxwl prep|run|clean|plan|mix|dbinfo|dbwatch --root DIR [tc.bin]")
	}
	cmd := os.Args[1]
	fs := flag.NewFlagSet(cmd, flag.ExitOnError)
	root := fs.String("root", "/data/local/tmp/uxwl", "재생 디렉터리")
	speed := fs.Float64("speed", 1, "재생 속도 배수")
	maxQD := fs.Int("max-qd", 256, "동시에 진행할 최대 요청 수")
	fs.IntVar(&maxWD, "max-wd", 1, "동시에 내는 O_DIRECT Write 수. 2 이상이면 f2fs 가 파일끼리 block 을 섞어 할당해 Write 가 4KB 로 쪼개진다 (11-05 까지 3)")
	out := fs.String("out", "", "결과 JSON (기본 <root>/result.json)")
	fs.BoolVar(&wakelock, "wakelock", true, "재생하는 동안 suspend 막기")
	var po planOpt
	packPath := fs.String("pack", "", "시나리오 함수 묶음 funcs.bin (plan, mix)")
	fs.StringVar(&po.weight, "weight", "", "유형 가중치 (실행 시간 비중), 예: sns=0.4,video=0.6")
	fs.StringVar(&po.fn, "func", "", "함수 하나만 실행 (plan 검증용)")
	fs.IntVar(&po.rep, "rep", 0, "--func 의 회차 (0부터)")
	fs.Float64Var(&po.sec, "sec", 7200, "TC 길이(초). 함수는 자르지 않아서 이보다 짧게 끝날 수 있다")
	fs.Float64Var(&po.rest, "rest", 20, "함수 사이 쉬는 초")
	fs.Float64Var(&po.lead, "lead", 5, "처음 쉬는 초")
	fs.Int64Var(&po.seed, "seed", 1, "같은 seed 면 같은 실행 순서")
	fs.StringVar(&po.out, "tc", "", "plan 이 쓸 tc.bin (기본 <root>/tc.bin)")
	fs.StringVar(&po.manifest, "manifest", "", "plan 이 쓸 실행 순서 JSON (기본 <root>/plan.json)")
	fs.Parse(os.Args[2:])
	if po.out == "" {
		po.out = filepath.Join(*root, "tc.bin")
	}
	if po.manifest == "" {
		po.manifest = filepath.Join(*root, "plan.json")
	}
	if *out == "" {
		*out = filepath.Join(*root, "result.json")
	}
	wbuf = aligned(maxIO)
	rand.New(rand.NewSource(1)).Read(wbuf)
	switch cmd {
	case "plan", "mix":
		if *packPath == "" {
			fatal("--pack 을 주세요")
		}
		must(os.MkdirAll(*root, 0o755))
		plan(loadPack(*packPath), po)
		if cmd == "mix" {
			files, reqs := load(po.out)
			loadSpecs(*root)
			must(os.RemoveAll(filepath.Join(*root, "f")))
			prep(*root, files)
			waitDiscard()
			run(*root, files, reqs, *speed, *maxQD, *out)
		}
	case "dbwatch":
		dbwatch(po.sec, po.out, fs.Args())
	case "dbinfo":
		if fs.NArg() < 1 {
			fatal("DB 파일을 주세요")
		}
		dbinfo(fs.Arg(0))
	case "trim":
		dfd, err := unix.Open(*root, unix.O_RDONLY|unix.O_DIRECTORY, 0)
		must(err)
		rg := [3]uint64{0, math.MaxUint64, 0}
		_, _, en := unix.Syscall(unix.SYS_IOCTL, uintptr(dfd), 0xC0185879, uintptr(unsafe.Pointer(&rg[0])))
		fmt.Printf("trim: errno=%d trimmed=%d bytes\n", en, rg[1])
	case "clean":
		must(os.RemoveAll(filepath.Join(*root, "f")))
		fmt.Println("clean: 지웠어요", *root)
	case "prep", "run":
		if fs.NArg() < 1 {
			fatal("TC 파일을 주세요")
		}
		files, reqs := load(fs.Arg(0))
		loadSpecs(*root)
		if cmd == "prep" {
			prep(*root, files)
		} else {
			run(*root, files, reqs, *speed, *maxQD, *out)
		}
	default:
		fatal("알 수 없는 명령 %s", cmd)
	}
}

func must(err error) {
	if err != nil {
		fatal("%v", err)
	}
}

func fatal(f string, a ...any) {
	fmt.Fprintf(os.Stderr, "uxwl: "+f+"\n", a...)
	os.Exit(1)
}
