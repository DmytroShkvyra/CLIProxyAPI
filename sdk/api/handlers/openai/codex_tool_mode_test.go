package openai

import (
	"testing"

	"github.com/router-for-me/CLIProxyAPI/v8/internal/config"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/registry"
	"github.com/router-for-me/CLIProxyAPI/v8/sdk/api/handlers"
)

func TestThirdPartyToolModePreservesNativeAndMixedRoutes(t *testing.T) {
	for _, mode := range []string{"", "direct", "invalid", "code_mode_only"} {
		t.Run(mode, func(t *testing.T) {
			models := []map[string]any{
				{"slug": "local", "tool_mode": "direct"},
				{"slug": "native", "tool_mode": "native-mode"},
				{"slug": "mixed", "tool_mode": "mixed-mode"},
				{"slug": "unknown", "tool_mode": "direct"},
			}
			routes := map[string][]string{
				"local":  {"openai-compatible-omlx"},
				"native": {"codex"},
				"mixed":  {"openai-compatible-vmlx", "codex"},
			}
			response := map[string]any{"models": models}
			applyThirdPartyToolMode(response, mode, func(id string) []string { return routes[id] })
			wantLocal := "direct"
			if mode == "code_mode_only" {
				wantLocal = mode
			}
			for i, want := range []string{wantLocal, "native-mode", "mixed-mode", "direct"} {
				if models[i]["tool_mode"] != want {
					t.Fatalf("%s tool_mode = %v, want %s", models[i]["slug"], models[i]["tool_mode"], want)
				}
			}
		})
	}
}

func TestCodexClientThirdPartyToolModeFollowsConfig(t *testing.T) {
	modelID := "third-party-tool-mode-test"
	clientID := modelID + "-client"
	reg := registry.GetGlobalRegistry()
	reg.RegisterClient(clientID, "openai-compatible-omlx", []*registry.ModelInfo{{ID: modelID}})
	t.Cleanup(func() { reg.UnregisterClient(clientID) })
	base := handlers.NewBaseAPIHandlers(&config.SDKConfig{}, nil)
	handler := NewOpenAIAPIHandler(base)
	for _, mode := range []string{"", "code_mode_only", "direct"} {
		base.Cfg.Client.Codex.ThirdPartyToolMode = mode
		response := handler.codexClientModelsResponse("0.167.0")
		models, _ := response["models"].([]map[string]any)
		found := false
		for _, model := range models {
			if model["slug"] != modelID {
				continue
			}
			found = true
			want := "direct"
			if mode == "code_mode_only" {
				want = mode
			}
			if model["tool_mode"] != want {
				t.Fatalf("got %v, want %s", model["tool_mode"], want)
			}
		}
		if !found {
			t.Fatal("local model missing from catalog")
		}
	}
}
