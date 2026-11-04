package main

// 시나리오 함수 묶음(funcs.bin, gen_funcs.py 가 만든다) → 실행 계획 → 재생
//
//	uxwl plan --pack funcs.bin --weight sns=0.4,video=0.6 --sec 7200 --seed 1 --out tc.bin --manifest plan.json
//	uxwl plan --pack funcs.bin --func A1 --rep 0 --out tc.bin --manifest plan.json     함수 하나만 (검증용)
//	uxwl mix  --pack funcs.bin --weight sns=0.4,video=0.6 --sec 7200 --seed 1          plan → prep → Discard 대기 → run
//
// 함수는 자르지 않고 끝까지 실행한다. 유형 선택은 choose 에 적어 두었다.
// 유형 안 함수는 비중대로, 회차는 고르게 무작위로 고른다. 같은 seed 면 tc.bin 이 바이트까지 같다.

import (
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
	"math/rand"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"

	"golang.org/x/sys/unix"
)

type packRep struct {
	Seg    string            `json:"seg"`
	DurSec float64           `json:"durSec"`
	Off    int64             `json:"off"`
	NFiles int               `json:"nfiles"`
	NReq   int               `json:"nreq"`
	Dbs    map[string]string `json:"dbs,omitempty"` // 파일 번호 → 실제 테이블 구조 이름
}

type packFunc struct {
	Name string    `json:"name"`
	Reps []packRep `json:"reps"`
}

type pack struct {
	Groups map[string]map[string]float64 `json:"groups"`
	Funcs  map[string]packFunc           `json:"funcs"`
	Specs  map[string]*dbSpec            `json:"specs"`
	f      *os.File
}

func loadPack(path string) *pack {
	f, err := os.Open(path)
	must(err)
	head := make([]byte, 12)
	_, err = io.ReadFull(f, head)
	must(err)
	if string(head[:8]) != "UXFN0001" {
		fatal("함수 묶음 형식이 아니에요: %s", path)
	}
	js := make([]byte, binary.LittleEndian.Uint32(head[8:]))
	_, err = io.ReadFull(f, js)
	must(err)
	p := &pack{f: f}
	must(json.Unmarshal(js, p))
	return p
}

type packFile struct {
	size  uint64
	flags uint8 // 1 = 원래 있던 파일, 2 = SQLite DB, 4 = rollback journal DB
}

func (p *pack) rep(r packRep) ([]packFile, []req) {
	b := make([]byte, r.NFiles*9+r.NReq*25)
	_, err := p.f.ReadAt(b, r.Off)
	must(err)
	files := make([]packFile, r.NFiles)
	for i := range files {
		files[i] = packFile{binary.LittleEndian.Uint64(b[i*9:]), b[i*9+8]}
	}
	b = b[r.NFiles*9:]
	reqs := make([]req, r.NReq)
	for i := range reqs {
		x := b[i*25:]
		reqs[i] = req{binary.LittleEndian.Uint64(x), x[8], binary.LittleEndian.Uint32(x[9:]), binary.LittleEndian.Uint64(x[13:]), binary.LittleEndian.Uint32(x[21:])}
	}
	return files, reqs
}

// 화면을 끄고 잰 시나리오 (gen_tc.py SCREEN_OFF 와 같음)
var screenOff = map[string]bool{"S1": true, "S2": true, "S3": true, "S5": true}

type planItem struct {
	I       int     `json:"i"`
	Seg     string  `json:"seg"`
	Func    string  `json:"func"`
	Name    string  `json:"name"`
	Cat     string  `json:"cat"`
	TcStart float64 `json:"tcStart"`
	SrcFrom float64 `json:"srcFrom"`
	SrcTo   float64 `json:"srcTo"`
}

type planner struct {
	p      *pack
	files  []tcFile
	reqs   []req
	items  []planItem
	specs  map[string]*dbSpec
	shared map[string]uint32 // 원래 있던 파일은 같은 회차를 다시 써도 같은 파일 (미리 채우는 양을 줄임)
}

func (b *planner) addFile(size uint64, flags uint8) uint32 {
	prefill := flags&1 != 0 && flags&dbFlagSQLite == 0
	b.files = append(b.files, tcFile{size, prefill, flags&^1 | map[bool]uint8{true: 1, false: 0}[prefill]})
	return uint32(len(b.files) - 1)
}

// 함수 하나를 tc 초부터 넣고 길이(초)를 돌려준다
func (b *planner) add(fn, cat string, r packRep, tc float64) float64 {
	files, reqs := b.p.rep(r)
	i := len(b.items)
	b.items = append(b.items, planItem{i, r.Seg, fn, b.p.Funcs[fn].Name, cat, tc, 0, r.DurSec})
	start := uint64(tc * 1e6)
	b.reqs = append(b.reqs, req{start, opMark, uint32(i), 0, 0})
	// 파일 번호는 조각의 파일 순서대로 (미리 채우는 순서가 블록 배치를 정해서 gen_tc.py 와 같게 둔다)
	seen := map[uint32]bool{}
	var used []uint32
	for _, x := range reqs {
		if x.op != opCP && x.op != opDS && !seen[x.file] {
			seen[x.file] = true
			used = append(used, x.file)
		}
	}
	sort.Slice(used, func(i, j int) bool { return used[i] < used[j] })
	gid := map[uint32]uint32{}
	for _, k := range used {
		f := files[k]
		if f.flags&1 != 0 {
			key := fmt.Sprintf("%s/%d", r.Seg, k)
			id, ok := b.shared[key]
			if !ok {
				id = b.addFile(f.size, f.flags)
				b.shared[key] = id
			}
			gid[k] = id
			if name := r.Dbs[fmt.Sprint(k)]; name != "" {
				b.specs[fmt.Sprint(id)] = b.p.Specs[name]
			}
		} else {
			gid[k] = b.addFile(f.size, f.flags)
		}
	}
	for _, x := range reqs {
		b.reqs = append(b.reqs, req{start + x.t, x.op, gid[x.file], x.off, x.ln})
	}
	return r.DurSec
}

func (b *planner) screen(tc float64, on bool) {
	v := uint32(0)
	if on {
		v = 1
	}
	t := int64(tc*1e6) - 1
	if t < 0 {
		t = 0
	}
	b.reqs = append(b.reqs, req{uint64(t), opScreen, v, 0, 0})
}

func parseWeights(s string) map[string]float64 {
	out := map[string]float64{}
	for _, kv := range strings.Split(s, ",") {
		k, v, ok := strings.Cut(strings.TrimSpace(kv), "=")
		w, err := strconv.ParseFloat(v, 64)
		if !ok || err != nil || w < 0 {
			fatal("--weight 형식은 sns=0.4,video=0.6 이에요: %q", kv)
		}
		if w > 0 {
			out[k] = w
		}
	}
	return out
}

type planOpt struct {
	weight, fn      string
	rep             int
	sec, rest, lead float64
	seed            int64
	out, manifest   string
}

func sortedKeys[V any](m map[string]V) []string {
	k := make([]string, 0, len(m))
	for x := range m {
		k = append(k, x)
	}
	sort.Strings(k)
	return k
}

type pick struct {
	fn, group string
	rep       packRep
}

// 유형 선택: 실행 시간 / 가중치 가 가장 작은 유형부터. 함수는 자르지 않으므로, 넣었을 때 유형 예산에 더 가까워지는 함수만 후보로 둔다
// (spent + 길이/2 <= 예산). 그래야 긴 함수 하나가 작은 유형의 비중을 크게 넘기지 않는다
func choose(p *pack, w map[string]float64, tot, budget float64, o planOpt) []pick {
	rng := rand.New(rand.NewSource(o.seed))
	spent := map[string]float64{}
	var out []pick
	used := 0.0
	for {
		left := budget - used
		var pickG string
		var cands []string
		best := 0.0
		for _, g := range sortedKeys(w) {
			room := w[g]/tot*budget - spent[g]
			var fit []string
			for _, fn := range sortedKeys(p.Groups[g]) {
				if d := minDur(p.Funcs[fn]); p.Groups[g][fn] > 0 && d <= left && d/2 <= room {
					fit = append(fit, fn)
				}
			}
			if len(fit) == 0 {
				continue
			}
			if r := spent[g] / w[g]; pickG == "" || r < best {
				pickG, best, cands = g, r, fit
			}
		}
		if pickG == "" {
			return out
		}
		sum := 0.0
		for _, fn := range cands {
			sum += p.Groups[pickG][fn]
		}
		u := rng.Float64() * sum
		fn := cands[len(cands)-1]
		for _, c := range cands {
			if u -= p.Groups[pickG][c]; u < 0 {
				fn = c
				break
			}
		}
		room := w[pickG]/tot*budget - spent[pickG]
		var fit []packRep
		for _, r := range p.Funcs[fn].Reps {
			if r.DurSec <= left && r.DurSec/2 <= room {
				fit = append(fit, r)
			}
		}
		r := fit[rng.Intn(len(fit))]
		out = append(out, pick{fn, pickG, r})
		spent[pickG] += r.DurSec
		used += r.DurSec
	}
}

// 실행 계획을 tc.bin 과 manifest 로 쓴다
func plan(p *pack, o planOpt) {
	b := &planner{p: p, shared: map[string]uint32{}, specs: map[string]*dbSpec{}}
	meta := map[string]any{"mode": "func", "seed": o.seed, "rest": o.rest, "lead": o.lead}
	t := o.lead
	end := t
	if o.fn != "" {
		fn, ok := p.Funcs[o.fn]
		if !ok || o.rep < 0 || o.rep >= len(fn.Reps) {
			fatal("함수 또는 회차가 없어요: %s rep %d", o.fn, o.rep)
		}
		cat := ""
		for g, m := range p.Groups {
			if _, ok := m[o.fn]; ok {
				cat = g
			}
		}
		b.screen(0, !screenOff[o.fn])
		end = t + b.add(o.fn, cat, fn.Reps[o.rep], t)
		meta["func"], meta["rep"] = o.fn, o.rep
	} else {
		w := parseWeights(o.weight)
		if len(w) == 0 {
			fatal("--weight 나 --func 를 주세요")
		}
		tot := 0.0
		for g, v := range w {
			if _, ok := p.Groups[g]; !ok {
				fatal("없는 유형이에요: %s (있는 유형: %s)", g, strings.Join(sortedKeys(p.Groups), ", "))
			}
			tot += v
		}
		// 쉬는 시간을 뺀 실행 시간을 유형에 나눠 준다. 함수 수에 따라 쉬는 시간이 달라지므로 몇 번 되풀이해 맞춘다
		var picks []pick
		budget := o.sec
		for k := 0; k < 4; k++ {
			picks = choose(p, w, tot, budget, o)
			if len(picks) == 0 {
				break
			}
			budget = o.sec - o.rest*float64(len(picks)-1)
		}
		spent := map[string]float64{}
		for k, c := range picks {
			if k > 0 {
				b.screen(t-o.rest/2, !screenOff[c.fn])
			} else {
				b.screen(0, !screenOff[c.fn])
			}
			d := b.add(c.fn, c.group, c.rep, t)
			spent[c.group] += d
			end = t + d
			t = end + o.rest
		}
		if len(b.items) == 0 {
			fatal("--sec 안에 들어가는 함수가 없어요")
		}
		var all float64
		for _, v := range spent {
			all += v
		}
		target, actual := map[string]float64{}, map[string]float64{}
		for g, v := range w {
			target[g] = v / tot
			actual[g] = spent[g] / all
		}
		meta["weight"], meta["target"], meta["actual"], meta["secByGroup"], meta["sec"] = o.weight, target, actual, spent, o.sec
		fmt.Println("유형           목표   실제   실행(초)")
		for _, g := range sortedKeys(w) {
			fmt.Printf("  %-12s %5.1f%% %5.1f%% %8.0f\n", g, 100*target[g], 100*actual[g], spent[g])
		}
	}
	b.reqs = append(b.reqs, req{uint64(end * 1e6), opMark, uint32(len(b.items) - 1), 0, 0}) // 끝 표시: 함수 끝의 Idle 까지 재생
	sort.SliceStable(b.reqs, func(i, j int) bool { return b.reqs[i].t < b.reqs[j].t })

	must(writeTC(o.out, b.files, b.reqs))
	sp, err := json.Marshal(b.specs)
	must(err)
	must(os.WriteFile(specPath(filepath.Dir(o.manifest)), sp, 0o644))
	var prefill uint64
	for _, f := range b.files {
		if f.prefill {
			prefill += f.size
		}
	}
	meta["timeline"], meta["files"], meta["requests"], meta["durSec"], meta["prefillMB"] = b.items, len(b.files), len(b.reqs), end, float64(prefill)/1e6
	js, err2 := json.MarshalIndent(meta, "", " ")
	err = err2
	must(err)
	must(os.WriteFile(o.manifest, js, 0o644))
	fmt.Printf("plan: 함수 %d번, %.0f초, request %d, 파일 %d (미리 채움 %.0fMB) → %s\n", len(b.items), end, len(b.reqs), len(b.files), float64(prefill)/1e6, o.out)
}

func minDur(f packFunc) float64 {
	m := f.Reps[0].DurSec
	for _, r := range f.Reps {
		if r.DurSec < m {
			m = r.DurSec
		}
	}
	return m
}

func writeTC(path string, files []tcFile, reqs []req) error {
	b := make([]byte, 0, 24+len(files)*9+len(reqs)*25)
	b = append(b, "UXWL0001"...)
	b = binary.LittleEndian.AppendUint32(b, uint32(len(files)))
	b = binary.LittleEndian.AppendUint32(b, 0)
	b = binary.LittleEndian.AppendUint64(b, uint64(len(reqs)))
	for _, f := range files {
		b = binary.LittleEndian.AppendUint64(b, f.size)
		b = append(b, f.flags)
	}
	for _, r := range reqs {
		b = binary.LittleEndian.AppendUint64(b, r.t)
		b = append(b, r.op)
		b = binary.LittleEndian.AppendUint32(b, r.file)
		b = binary.LittleEndian.AppendUint64(b, r.off)
		b = binary.LittleEndian.AppendUint32(b, r.ln)
	}
	return os.WriteFile(path, b, 0o644)
}

// 앞 실행이 지운 파일의 Discard 가 재생 앞부분에 섞이지 않게, f2fs 가 스스로 비울 때까지 기다린다 (run_tc.py 와 같음)
func waitDiscard() {
	start := time.Now()
	for time.Since(start) < 15*time.Minute {
		unix.Sync()
		ps, _ := filepath.Glob("/sys/fs/f2fs/*/pending_discard")
		var n int64
		for _, p := range ps {
			if b, err := os.ReadFile(p); err == nil {
				v, _ := strconv.ParseInt(strings.TrimSpace(string(b)), 10, 64)
				n += v
			}
		}
		if n == 0 {
			break
		}
		time.Sleep(10 * time.Second)
	}
	fmt.Printf("Discard 대기 %.0fs\n", time.Since(start).Seconds())
}
