import { useEffect } from "react";
import { UserManager } from "oidc-client-ts";

/**
 * Fallback silent-renew target: only reached if oidc-client-ts couldn't renew via the
 * refresh_token grant directly (the normal, no-iframe path) and fell back to an iframe-based
 * renewal instead. Runs in a hidden iframe, so it must not render the app UI.
 */
export function SilentRenew() {
  useEffect(() => {
    const userManager = new UserManager({
      authority: `${import.meta.env.VITE_KEYCLOAK_URL}/realms/${import.meta.env.VITE_KEYCLOAK_REALM}`,
      client_id: import.meta.env.VITE_KEYCLOAK_CLIENT_ID,
      redirect_uri: `${window.location.origin}/callback`,
    });
    void userManager.signinSilentCallback();
  }, []);

  return null;
}
