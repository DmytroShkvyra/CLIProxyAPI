package configaccess

import (
	"context"
	"net/http"
	"testing"

	sdkaccess "github.com/router-for-me/CLIProxyAPI/v8/sdk/access"
)

func newAuthRequest(t *testing.T, mutate func(*http.Request)) *http.Request {
	t.Helper()
	req, err := http.NewRequest(http.MethodPost, "http://127.0.0.1:18473/v1/responses", nil)
	if err != nil {
		t.Fatalf("NewRequest: %v", err)
	}
	if mutate != nil {
		mutate(req)
	}
	return req
}

func TestAuthenticateAcceptsXCodexLocalGatewayHeader(t *testing.T) {
	provider := newProvider(sdkaccess.DefaultAccessProviderName, []string{"client-key"})
	req := newAuthRequest(t, func(req *http.Request) {
		req.Header.Set("X-Codex-Local-Gateway", "client-key")
	})
	result, authErr := provider.Authenticate(context.Background(), req)
	if authErr != nil {
		t.Fatalf("Authenticate() error = %v, want nil", authErr)
	}
	if result == nil || result.Principal != "client-key" {
		t.Fatalf("Authenticate() result = %+v, want principal client-key", result)
	}
	if result.Metadata["source"] != "x-codex-local-gateway" {
		t.Fatalf("source metadata = %q, want x-codex-local-gateway", result.Metadata["source"])
	}
}

func TestAuthenticateAcceptsBearerToken(t *testing.T) {
	provider := newProvider(sdkaccess.DefaultAccessProviderName, []string{"client-key"})
	req := newAuthRequest(t, func(req *http.Request) {
		req.Header.Set("Authorization", "Bearer client-key")
	})
	result, authErr := provider.Authenticate(context.Background(), req)
	if authErr != nil {
		t.Fatalf("Authenticate() error = %v, want nil", authErr)
	}
	if result == nil || result.Principal != "client-key" {
		t.Fatalf("Authenticate() result = %+v, want principal client-key", result)
	}
}

func TestAuthenticateAcceptsHeaderBesideJWTBearer(t *testing.T) {
	provider := newProvider(sdkaccess.DefaultAccessProviderName, []string{"client-key"})
	req := newAuthRequest(t, func(req *http.Request) {
		req.Header.Set("Authorization", "Bearer eyJhbGciOiJSUzI1NiJ9.session.signature")
		req.Header.Set("X-Codex-Local-Gateway", "client-key")
	})
	result, authErr := provider.Authenticate(context.Background(), req)
	if authErr != nil {
		t.Fatalf("Authenticate() error = %v, want nil", authErr)
	}
	if result == nil || result.Principal != "client-key" {
		t.Fatalf("Authenticate() result = %+v, want principal client-key", result)
	}
}

func TestAuthenticateRejectsUnknownKeyInHeader(t *testing.T) {
	provider := newProvider(sdkaccess.DefaultAccessProviderName, []string{"client-key"})
	req := newAuthRequest(t, func(req *http.Request) {
		req.Header.Set("X-Codex-Local-Gateway", "other-key")
	})
	_, authErr := provider.Authenticate(context.Background(), req)
	if authErr == nil || !sdkaccess.IsAuthErrorCode(authErr, sdkaccess.AuthErrorCodeInvalidCredential) {
		t.Fatalf("Authenticate() error = %v, want invalid credential", authErr)
	}
}

func TestAuthenticateReportsMissingCredentials(t *testing.T) {
	provider := newProvider(sdkaccess.DefaultAccessProviderName, []string{"client-key"})
	req := newAuthRequest(t, nil)
	_, authErr := provider.Authenticate(context.Background(), req)
	if authErr == nil || !sdkaccess.IsAuthErrorCode(authErr, sdkaccess.AuthErrorCodeNoCredentials) {
		t.Fatalf("Authenticate() error = %v, want no credentials", authErr)
	}
}
