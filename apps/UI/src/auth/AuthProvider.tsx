import type { ReactNode } from "react";
import { AuthProvider as OidcAuthProvider } from "react-oidc-context";
import { useNavigate } from "react-router-dom";

/**
 * OIDC Authorization Code + PKCE against the mm-rag Keycloak realm's public mm-rag-ui
 * client (specs/071-search-frontend/plan.md) — react-oidc-context/oidc-client-ts handle
 * PKCE and silent token renewal; no custom token storage code here.
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();

  return (
    <OidcAuthProvider
      authority={`${import.meta.env.VITE_KEYCLOAK_URL}/realms/${import.meta.env.VITE_KEYCLOAK_REALM}`}
      client_id={import.meta.env.VITE_KEYCLOAK_CLIENT_ID}
      redirect_uri={`${window.location.origin}/callback`}
      scope="openid profile email"
      post_logout_redirect_uri={window.location.origin}
      automaticSilentRenew
      silent_redirect_uri={`${window.location.origin}/silent-renew`}
      onSigninCallback={() => {
        navigate("/workspaces", { replace: true });
      }}
    >
      {children}
    </OidcAuthProvider>
  );
}
