package openai

import (
	"strings"

	codexmodels "github.com/router-for-me/CLIProxyAPI/v8/internal/client/codex/models"
	"github.com/router-for-me/CLIProxyAPI/v8/internal/registry"
	responsesclaude "github.com/router-for-me/CLIProxyAPI/v8/internal/translator/claude/openai/responses"
)

func (h *OpenAIAPIHandler) codexClientModelsResponse(clientVersion ...string) map[string]any {
	version := ""
	if len(clientVersion) > 0 {
		version = clientVersion[0]
	}
	optimizeMultiAgentV2 := false
	thirdPartyToolMode := ""
	var applyPatchCapabilityForModel codexmodels.ApplyPatchCapabilityForModelFunc
	if h != nil {
		if cfg := h.CurrentConfig(); cfg != nil {
			optimizeMultiAgentV2 = cfg.Client.Codex.OptimizeMultiAgentV2
			thirdPartyToolMode = cfg.Client.Codex.ThirdPartyToolMode
			if cfg.Client.Codex.EnableApplyPatch {
				applyPatchCapabilityForModel = h.SupportsApplyPatchModel
			}
		}
	}
	var toolSearchCapabilityForModel codexmodels.ToolSearchCapabilityForModelFunc
	if h != nil && responsesclaude.ClientToolSearchEnabled() {
		toolSearchCapabilityForModel = h.SupportsNativeToolSearchModel
	}
	modelRegistry := registry.GetGlobalRegistry()
	response := codexmodels.BuildResponseForClientWithToolCapabilities(h.Models(), modelRegistry.GetModelProviders, modelRegistry.GetResponsesWebSearchCapability, applyPatchCapabilityForModel, toolSearchCapabilityForModel, optimizeMultiAgentV2, version)
	applyThirdPartyToolMode(response, thirdPartyToolMode, modelRegistry.GetModelProviders)
	return response
}

// applyThirdPartyToolMode only opts exclusively third-party routes into code mode.
// Native and mixed Codex routes retain their catalog capabilities.
func applyThirdPartyToolMode(response map[string]any, mode string, providersForModel func(string) []string) {
	if strings.TrimSpace(mode) != "code_mode_only" || providersForModel == nil {
		return
	}
	models, _ := response["models"].([]map[string]any)
	for _, model := range models {
		slug, _ := model["slug"].(string)
		providers := providersForModel(slug)
		thirdParty := len(providers) > 0
		for _, provider := range providers {
			if strings.EqualFold(strings.TrimSpace(provider), "codex") {
				thirdParty = false
			}
		}
		if thirdParty {
			model["tool_mode"] = "code_mode_only"
		}
	}
}

// CodexClientModelsResponse builds a Codex client model response.
func CodexClientModelsResponse(models []map[string]any) map[string]any {
	return codexmodels.BuildResponse(models, nil, false)
}

// CodexClientModelsResponseWithMultiAgentV2 builds a Codex client model response
// and advertises multi-agent v2 for synthesized models when enabled.
func CodexClientModelsResponseWithMultiAgentV2(models []map[string]any, enabled bool) map[string]any {
	return codexmodels.BuildResponse(models, nil, enabled)
}

// CodexClientModelsResponseForClient builds a Codex client model response
// tailored for a specific client version.
func CodexClientModelsResponseForClient(models []map[string]any, clientVersion string, enabled bool) map[string]any {
	return codexmodels.BuildResponseForClient(models, nil, enabled, clientVersion)
}
