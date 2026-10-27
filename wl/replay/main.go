// uxwl: UX workload TC 재생기 (기기에서 실행, root)
//
//	uxwl prep  --root /data/local/tmp/uxwl tc.bin   미리 있어야 하는 파일을 만들고 채운 뒤 page cache 를 비운다
//	uxwl run   --root /data/local/tmp/uxwl tc.bin   시각에 맞춰 파일 동작을 재생하고 result.json 을 쓴다
//	uxwl clean --root /data/local/tmp/uxwl          재생 디렉터리를 지운다
//
// TC 형식 (little endian, gen_tc.py 가 만든다)
//
//	header  "UXWL0001" | nfiles u32 | 0 u32 | nreq u64
//	files   size u64 | flags u8 (1 = prefill)
//	reqs    t_us u64 | op u8 | file u32 | off u64 | len u32
//
// op: 0 R(O_DIRECT pread) 1 W(pwrite+sync_file_range) 2 WB(pwrite) 3 WD(O_DIRECT pwrite)
//
//	4 FS(fsync) 6 UNLINK 7 TRUNC(off=새 크기) 8 MARK(file=타임라인 구간 번호)
//	9 FA(atomic commit: F2FS_IOC_COMMIT_ATOMIC_WRITE) 10 WX(atomic write 안 pwrite, 처음이면 START_ATOMIC_WRITE)
//	11 CP(디렉터리 fsync → f2fs Checkpoint) 12 TRIM(FITRIM: 지운 파일의 블록을 f2fs 가 Discard 로 반납)
//	13 DS(fsync 뒤 디렉터리 fsync: SQLite 새 journal·AtomicFile 이 하는 것. 동작은 CP 와 같고 원인이 있는 쪽)
//	14 SCREEN(file=1 켜기: 깨우고 잠금 해제, 켜 있는 동안 10초마다 깨우기 / 0 끄기)
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
	"os/exec"
	"os"
	"path/filepath"
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
	nOps
)

// include/uapi/linux/f2fs.h: _IO(0xf5, 1), _IO(0xf5, 2)
const (
	f2fsStartAtomic  = 0xf501
	f2fsCommitAtomic = 0xf502
)

var opName = [nOps]string{"R", "W", "WB", "WD", "FS", "", "UNLINK", "TRUNC", "MARK", "FA", "WX", "CP", "TRIM", "DS", "SCREEN"}

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
}

func load(path string) ([]tcFile, []req) {
	f, err := os.Open(path)
	must(err)
	defer f.Close()
	r := bufio.NewReaderSize(f, 1<<20)
	var magic [8]byte
	_, err = io.ReadFull(r, magic[:])
	must(err)
	if string(magic[:]) != "UXWL0001" {
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
		_, err = io.ReadFull(r, b[:9])
		must(err)
		files[i] = tcFile{binary.LittleEndian.Uint64(b), b[8]&1 != 0}
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

var maxWD = 3

var wbuf []byte // Write 내용 (난수, 읽기 전용으로 공유)

var (
	errMu    sync.Mutex
	errKinds = map[string]int{}
)

func fpath(root string, id uint32) string { return filepath.Join(root, "f", fmt.Sprintf("%06d", id)) }

func prep(root string, files []tcFile) {
	must(os.MkdirAll(filepath.Join(root, "f"), 0o755))
	var need, done uint64
	for _, f := range files {
		if f.prefill {
			need += f.size
		}
	}
	start := time.Now()
	for id, f := range files {
		p := fpath(root, uint32(id))
		if !f.prefill {
			os.Remove(p) // 새로 만들 파일은 없는 상태로 시작
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
		fd, err := unix.Open(fpath(s.root, id), fl, 0o644)
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

func run(root string, files []tcFile, reqs []req, speed float64, maxQD int, out string) {
	s := &store{root: root, m: map[uint32]*ofile{}}
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
	exec := func(r req, sg *segStat) {
		f := s.get(r.file)
		// WD 도 파일마다 하나씩: 앱은 파일 하나를 스레드 하나가 순서대로 쓴다. 동시에 쓰면 f2fs 가 파일끼리 블록을 섞어 할당해 Write 가 4KB 로 쪼개진다
		excl := r.op == opFS || r.op == opUnlink || r.op == opTrunc || r.op == opFA || r.op == opWX || r.op == opWD
		if excl {
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
		ns := time.Since(st).Nanoseconds()
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
		j := i + 1
		if r.op == opR || r.op == opW || r.op == opWD {
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
		go func(grp []req, sg *segStat) {
			defer func() { atomic.AddInt64(&qd, -1); <-sem; wg.Done() }()
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
// 화면 꺼짐 시간(30초)보다 자주 깨우기 키를 보내 켜진 상태를 유지한다 (설정은 바꾸지 않는다)
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
					sh("input keyevent KEYCODE_WAKEUP")
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
		fatal("usage: uxwl prep|run|clean --root DIR [tc.bin]")
	}
	cmd := os.Args[1]
	fs := flag.NewFlagSet(cmd, flag.ExitOnError)
	root := fs.String("root", "/data/local/tmp/uxwl", "재생 디렉터리")
	speed := fs.Float64("speed", 1, "재생 속도 배수")
	maxQD := fs.Int("max-qd", 256, "동시에 진행할 최대 요청 수")
	fs.IntVar(&maxWD, "max-wd", 3, "동시에 O_DIRECT 로 쓰는 파일 수 (앱의 쓰기 스레드 수). 많으면 f2fs 가 파일끼리 블록을 섞어 할당해 Write 가 4KB 로 쪼개진다")
	out := fs.String("out", "", "결과 JSON (기본 <root>/result.json)")
	fs.BoolVar(&wakelock, "wakelock", true, "재생하는 동안 suspend 막기")
	fs.Parse(os.Args[2:])
	if *out == "" {
		*out = filepath.Join(*root, "result.json")
	}
	wbuf = aligned(maxIO)
	rand.New(rand.NewSource(1)).Read(wbuf)
	switch cmd {
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
