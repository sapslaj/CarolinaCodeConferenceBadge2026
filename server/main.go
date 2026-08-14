package main

import (
	"crypto/sha256"
	_ "embed"
	"encoding/hex"
	"encoding/json"
	"io"
	"io/fs"
	"log/slog"
	"net/http"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"
)

//go:embed admin.html
var adminHTML []byte

var logger = slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
	Level: slog.LevelInfo,
}))

// ---- Types ----

type Badge struct {
	Name     string    `json:"name"`
	Mood     string    `json:"mood"`
	LastSeen time.Time `json:"last_seen"`
}

type Broadcast struct {
	Text  string `json:"text"`
	Color string `json:"color"`
}

type LightCommand struct {
	Pattern string `json:"pattern"`
	Color   string `json:"color"`
}

type Poll struct {
	Active   bool              `json:"active"`
	Question string            `json:"question"`
	Options  []string          `json:"options"`
	Votes    map[string]string `json:"-"`
}

type TelemetryEntry struct {
	Time      time.Time `json:"time"`
	ID        string    `json:"id"`
	FirstName string    `json:"first_name"`
	LastName  string    `json:"last_name"`
	Message   string    `json:"message"`
}

// telemetryCap bounds the in-memory ring buffer so a badge stuck in a
// retry loop can't grow this without limit -- old entries just fall off.
const telemetryCap = 500

type ServerState struct {
	mu        sync.RWMutex
	broadcast Broadcast
	lights    LightCommand
	poll      Poll
	badges    map[string]*Badge
	telemetry []TelemetryEntry
}

// ---- API Request types ----

type CheckinRequest struct {
	ID   string `json:"id"`
	Name string `json:"name"`
}

type MoodRequest struct {
	ID   string `json:"id"`
	Mood string `json:"mood"`
}

type VoteRequest struct {
	ID     string `json:"id"`
	Option string `json:"option"`
}

type BroadcastRequest struct {
	Text  string `json:"text"`
	Color string `json:"color"`
}

type LightsRequest struct {
	Pattern string `json:"pattern"`
	Color   string `json:"color"`
}

type PollRequest struct {
	Question string   `json:"question"`
	Options  []string `json:"options"`
}

type TelemetryRequest struct {
	ID        string `json:"id"`
	FirstName string `json:"first_name"`
	LastName  string `json:"last_name"`
	Message   string `json:"message"`
}

// ---- API Response types ----

type StateResponse struct {
	Broadcast Broadcast      `json:"broadcast"`
	Lights    LightCommand   `json:"lights"`
	Poll      PollResponse   `json:"poll"`
	Mood      map[string]int `json:"mood"`
	Online    int            `json:"online"`
}

type PollResponse struct {
	Active   bool           `json:"active"`
	Question string         `json:"question"`
	Options  []string       `json:"options"`
	Tally    map[string]int `json:"tally"`
}

// ---- State helpers ----

func NewServerState() *ServerState {
	return &ServerState{
		badges: make(map[string]*Badge),
		lights: LightCommand{Pattern: "off", Color: "#000000"},
		poll:   Poll{Votes: make(map[string]string)},
	}
}

func (s *ServerState) cleanupStale() {
	cutoff := time.Now().Add(-30 * time.Second)
	for id, b := range s.badges {
		if b.LastSeen.Before(cutoff) {
			delete(s.badges, id)
		}
	}
}

func (s *ServerState) roomMood() map[string]int {
	moods := make(map[string]int)
	for _, b := range s.badges {
		if b.Mood != "" {
			moods[b.Mood]++
		}
	}
	return moods
}

func pollTally(poll Poll) map[string]int {
	tally := make(map[string]int)
	for _, opt := range poll.Options {
		tally[opt] = 0
	}
	for _, opt := range poll.Votes {
		tally[opt]++
	}
	return tally
}

// ---- Helpers ----

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(v)
}

func envOr(key, fallback string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return fallback
}

// ---- Badge handlers ----

func handleState(s *ServerState) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		s.mu.Lock()

		id := r.URL.Query().Get("id")
		if id != "" {
			if b, ok := s.badges[id]; ok {
				b.LastSeen = time.Now()
			}
		}
		s.cleanupStale()

		resp := StateResponse{
			Broadcast: s.broadcast,
			Lights:    s.lights,
			Poll: PollResponse{
				Active:   s.poll.Active,
				Question: s.poll.Question,
				Options:  s.poll.Options,
				Tally:    pollTally(s.poll),
			},
			Mood:   s.roomMood(),
			Online: len(s.badges),
		}

		s.mu.Unlock()
		writeJSON(w, resp)
	}
}

func handleCheckin(s *ServerState) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var req CheckinRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		if req.ID == "" {
			http.Error(w, "missing id", http.StatusBadRequest)
			return
		}

		s.mu.Lock()
		if b, ok := s.badges[req.ID]; ok {
			b.Name = req.Name
			b.LastSeen = time.Now()
		} else {
			s.badges[req.ID] = &Badge{
				Name:     req.Name,
				LastSeen: time.Now(),
			}
			logger.Info("badge checked in", "id", req.ID, "name", req.Name)
		}
		s.mu.Unlock()

		writeJSON(w, map[string]any{"ok": true})
	}
}

func handleMood(s *ServerState) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var req MoodRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}

		s.mu.Lock()
		if b, ok := s.badges[req.ID]; ok {
			b.Mood = req.Mood
			b.LastSeen = time.Now()
		}
		s.mu.Unlock()

		writeJSON(w, map[string]any{"ok": true})
	}
}

// handleTelemetry is a debug backchannel: badges log free-text messages
// here so problems (like OTA silently not applying) can be diagnosed while
// running untethered on battery, with no serial console available.
func handleTelemetry(s *ServerState) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var req TelemetryRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}
		if req.Message == "" {
			http.Error(w, "missing message", http.StatusBadRequest)
			return
		}

		entry := TelemetryEntry{
			Time:      time.Now(),
			ID:        req.ID,
			FirstName: req.FirstName,
			LastName:  req.LastName,
			Message:   req.Message,
		}

		logger.Info("badge telemetry",
			"id", req.ID, "first_name", req.FirstName, "last_name", req.LastName,
			"message", req.Message)

		s.mu.Lock()
		s.telemetry = append(s.telemetry, entry)
		if len(s.telemetry) > telemetryCap {
			s.telemetry = s.telemetry[len(s.telemetry)-telemetryCap:]
		}
		s.mu.Unlock()

		writeJSON(w, map[string]any{"ok": true})
	}
}

func handleVote(s *ServerState) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var req VoteRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}

		s.mu.Lock()
		if s.poll.Active {
			s.poll.Votes[req.ID] = req.Option
			if b, ok := s.badges[req.ID]; ok {
				b.LastSeen = time.Now()
			}
			logger.Info("vote", "badge", req.ID, "option", req.Option)
		}
		s.mu.Unlock()

		writeJSON(w, map[string]any{"ok": true})
	}
}

// ---- Admin handlers ----

func handleAdminBroadcast(s *ServerState) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var req BroadcastRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}

		s.mu.Lock()
		s.broadcast = Broadcast{Text: req.Text, Color: req.Color}
		s.mu.Unlock()

		logger.Info("broadcast set", "text", req.Text, "color", req.Color)
		writeJSON(w, map[string]any{"ok": true})
	}
}

func handleAdminLights(s *ServerState) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var req LightsRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}

		s.mu.Lock()
		s.lights = LightCommand{Pattern: req.Pattern, Color: req.Color}
		s.mu.Unlock()

		logger.Info("lights set", "pattern", req.Pattern, "color", req.Color)
		writeJSON(w, map[string]any{"ok": true})
	}
}

func handleAdminPollStart(s *ServerState) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var req PollRequest
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
			http.Error(w, "bad request", http.StatusBadRequest)
			return
		}

		s.mu.Lock()
		s.poll = Poll{
			Active:   true,
			Question: req.Question,
			Options:  req.Options,
			Votes:    make(map[string]string),
		}
		s.mu.Unlock()

		logger.Info("poll started", "question", req.Question)
		writeJSON(w, map[string]any{"ok": true})
	}
}

func handleAdminPollStop(s *ServerState) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		s.mu.Lock()
		s.poll = Poll{Votes: make(map[string]string)}
		s.mu.Unlock()

		logger.Info("poll stopped")
		writeJSON(w, map[string]any{"ok": true})
	}
}

func handleAdminBadges(s *ServerState) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		s.mu.Lock()
		s.cleanupStale()

		type badgeInfo struct {
			ID       string `json:"id"`
			Name     string `json:"name"`
			Mood     string `json:"mood"`
			LastSeen string `json:"last_seen"`
		}

		badges := make([]badgeInfo, 0, len(s.badges))
		for id, b := range s.badges {
			badges = append(badges, badgeInfo{
				ID:       id,
				Name:     b.Name,
				Mood:     b.Mood,
				LastSeen: b.LastSeen.Format(time.RFC3339),
			})
		}
		s.mu.Unlock()

		writeJSON(w, badges)
	}
}

// handleAdminTelemetry serves the most recent entries newest-first, so
// this can be watched from a browser (the admin UI) with no shell access
// to the pod -- the point of the endpoint in the first place.
func handleAdminTelemetry(s *ServerState) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		s.mu.RLock()
		out := make([]TelemetryEntry, len(s.telemetry))
		for i, e := range s.telemetry {
			out[len(s.telemetry)-1-i] = e
		}
		s.mu.RUnlock()

		writeJSON(w, out)
	}
}

// ---- OTA ----
//
// Badges pull updates straight from the server across four kinds of
// content -- samples/, lib/, mods/, and tools/ -- each rooted at its own
// directory.
// Within a kind, every top-level entry (a sample folder, a lib package
// folder, a lone .mpy) becomes a "unit" hashed into the manifest, and
// BadgeHub compares that against what it last applied. Redeploying the
// server with new content is what ships an update -- there is no separate
// publish step.

type OTAFile struct {
	Path   string `json:"path"`
	SHA256 string `json:"sha256"`
	Size   int64  `json:"size"`
}

// OTAUnit is one top-level entry within a kind -- a sample folder, a lib
// package folder, or a single top-level file (e.g. lib/neopixel.mpy). Its
// Files' Paths are relative to the *kind's* root, not the unit, so a file
// can be fetched with nothing beyond (kind, path).
type OTAUnit struct {
	Hash  string    `json:"hash"`
	Files []OTAFile `json:"files"`
}

type OTAKind struct {
	Units map[string]OTAUnit `json:"units"`
}

type OTAManifest struct {
	Kinds map[string]OTAKind `json:"kinds"`
}

type OTAStore struct {
	roots    map[string]string // kind -> root dir
	manifest OTAManifest
}

// collectDirFiles walks root and returns every file under it, Path relative
// to root.
func collectDirFiles(root string) ([]OTAFile, error) {
	var files []OTAFile
	err := filepath.WalkDir(root, func(path string, d fs.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if d.IsDir() {
			return nil
		}
		rel, err := filepath.Rel(root, path)
		if err != nil {
			return err
		}
		rel = filepath.ToSlash(rel)
		data, err := os.ReadFile(path)
		if err != nil {
			return err
		}
		sum := sha256.Sum256(data)
		files = append(files, OTAFile{
			Path:   rel,
			SHA256: hex.EncodeToString(sum[:]),
			Size:   int64(len(data)),
		})
		return nil
	})
	return files, err
}

func hashUnit(files []OTAFile) string {
	sort.Slice(files, func(i, j int) bool { return files[i].Path < files[j].Path })
	h := sha256.New()
	for _, f := range files {
		io.WriteString(h, f.Path)
		io.WriteString(h, f.SHA256)
	}
	return hex.EncodeToString(h.Sum(nil))
}

// collectKindUnits treats every top-level entry of root as its own unit. A
// directory entry is walked recursively with its files prefixed by the
// entry's name (e.g. "adafruit_bitmap_font/bdf.mpy"); a top-level file is a
// one-file unit whose single file's Path is just its own name (e.g.
// "neopixel.mpy"). Either way every OTAFile.Path returned is relative to
// root, so it can be fetched directly.
func collectKindUnits(root string) (map[string]OTAUnit, error) {
	entries, err := os.ReadDir(root)
	if err != nil {
		return nil, err
	}

	units := make(map[string]OTAUnit)
	for _, e := range entries {
		name := e.Name()
		if strings.HasPrefix(name, ".") {
			continue
		}

		var files []OTAFile
		if e.IsDir() {
			sub, err := collectDirFiles(filepath.Join(root, name))
			if err != nil {
				logger.Warn("failed to hash OTA unit, skipping", "unit", name, "error", err)
				continue
			}
			for _, f := range sub {
				files = append(files, OTAFile{
					Path:   name + "/" + f.Path,
					SHA256: f.SHA256,
					Size:   f.Size,
				})
			}
		} else {
			data, err := os.ReadFile(filepath.Join(root, name))
			if err != nil {
				logger.Warn("failed to hash OTA unit, skipping", "unit", name, "error", err)
				continue
			}
			sum := sha256.Sum256(data)
			files = []OTAFile{{
				Path:   name,
				SHA256: hex.EncodeToString(sum[:]),
				Size:   int64(len(data)),
			}}
		}

		if len(files) == 0 {
			continue
		}
		units[name] = OTAUnit{Hash: hashUnit(files), Files: files}
	}
	return units, nil
}

// loadOTAStore hashes every kind's directory once at startup. A missing or
// empty kind directory is not fatal -- that kind is simply left out of the
// manifest and the rest of the badge server keeps working.
func loadOTAStore(roots map[string]string) *OTAStore {
	manifest := OTAManifest{Kinds: make(map[string]OTAKind)}

	for kind, dir := range roots {
		units, err := collectKindUnits(dir)
		if err != nil {
			logger.Warn("OTA kind directory unavailable, skipping", "kind", kind, "dir", dir, "error", err)
			continue
		}
		manifest.Kinds[kind] = OTAKind{Units: units}
		logger.Info("OTA manifest built", "kind", kind, "dir", dir, "units", len(units))
	}

	return &OTAStore{roots: roots, manifest: manifest}
}

func handleOTAManifest(store *OTAStore) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, store.manifest)
	}
}

func handleOTAFile(store *OTAStore) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		kind := r.URL.Query().Get("kind")
		reqPath := r.URL.Query().Get("path")

		root, ok := store.roots[kind]
		if !ok {
			http.Error(w, "unknown kind", http.StatusNotFound)
			return
		}
		kindManifest, ok := store.manifest.Kinds[kind]
		if !ok {
			http.Error(w, "unknown kind", http.StatusNotFound)
			return
		}

		clean := filepath.ToSlash(filepath.Clean(reqPath))
		if clean == "." || strings.HasPrefix(clean, "../") || strings.HasPrefix(clean, "/") {
			http.Error(w, "bad path", http.StatusBadRequest)
			return
		}

		found := false
		for _, unit := range kindManifest.Units {
			for _, f := range unit.Files {
				if f.Path == clean {
					found = true
					break
				}
			}
			if found {
				break
			}
		}
		if !found {
			http.Error(w, "unknown file", http.StatusNotFound)
			return
		}

		full := filepath.Join(root, filepath.FromSlash(clean))
		w.Header().Set("Content-Type", "application/octet-stream")
		http.ServeFile(w, r, full)
	}
}

// ---- Static handlers ----

func handleAdminUI(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "text/html")
	w.Write(adminHTML)
}

func handleLiveness(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, map[string]any{"status": "ok"})
}

func handleReadiness(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, map[string]any{"status": "ok"})
}

// ---- Logging middleware ----

type responseRecorder struct {
	http.ResponseWriter
	status int
}

func (rr *responseRecorder) WriteHeader(code int) {
	rr.status = code
	rr.ResponseWriter.WriteHeader(code)
}

func loggingMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		rr := &responseRecorder{ResponseWriter: w, status: 200}
		next.ServeHTTP(rr, r)
		logger.Info("request",
			"method", r.Method,
			"path", r.URL.Path,
			"status", rr.status,
			"duration", time.Since(start),
			"ip", r.RemoteAddr,
		)
	})
}

// ---- Main ----

func main() {
	state := NewServerState()

	otaStore := loadOTAStore(map[string]string{
		"samples": envOr("SAMPLES_DIR", "/samples"),
		"lib":     envOr("LIB_DIR", "/lib"),
		"mods":    envOr("MODS_DIR", "/mods"),
		"tools":   envOr("TOOLS_DIR", "/tools"),
	})

	mux := http.NewServeMux()
	mux.HandleFunc("GET /api/state", handleState(state))
	mux.HandleFunc("POST /api/checkin", handleCheckin(state))
	mux.HandleFunc("POST /api/mood", handleMood(state))
	mux.HandleFunc("POST /api/vote", handleVote(state))
	mux.HandleFunc("POST /api/admin/broadcast", handleAdminBroadcast(state))
	mux.HandleFunc("POST /api/admin/lights", handleAdminLights(state))
	mux.HandleFunc("POST /api/admin/poll", handleAdminPollStart(state))
	mux.HandleFunc("DELETE /api/admin/poll", handleAdminPollStop(state))
	mux.HandleFunc("GET /api/admin/badges", handleAdminBadges(state))
	mux.HandleFunc("POST /api/telemetry", handleTelemetry(state))
	mux.HandleFunc("GET /api/admin/telemetry", handleAdminTelemetry(state))
	mux.HandleFunc("GET /api/ota/manifest", handleOTAManifest(otaStore))
	mux.HandleFunc("GET /api/ota/file", handleOTAFile(otaStore))
	mux.HandleFunc("GET /healthz/liveness", handleLiveness)
	mux.HandleFunc("GET /healthz/readiness", handleReadiness)
	mux.HandleFunc("GET /", handleAdminUI)

	handler := loggingMiddleware(mux)

	addr := os.Getenv("LISTEN_ADDR")
	if addr == "" {
		addr = ":8080"
	}

	logger.Info("starting badge server", "listen_addr", addr)
	if err := http.ListenAndServe(addr, handler); err != nil {
		logger.Error("server failed", "error", err)
		os.Exit(1)
	}
}
