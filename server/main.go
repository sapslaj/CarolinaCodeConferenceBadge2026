package main

import (
	_ "embed"
	"encoding/json"
	"log/slog"
	"net/http"
	"os"
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

type ServerState struct {
	mu        sync.RWMutex
	broadcast Broadcast
	lights    LightCommand
	poll      Poll
	badges    map[string]*Badge
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
