import { Center, Loader } from "@mantine/core";
import { useEffect } from "react";
import { useAuth } from "react-oidc-context";
import { Outlet } from "react-router-dom";

/**
 * Route guard: redirects an unauthenticated visitor to Keycloak login. The actual
 * authorization decision (what a caller may do once authenticated) always stays
 * server-side in apps/api's require_workspace_role — this only gates client-side
 * navigation to avoid rendering pages with no session to call the API with.
 */
export function RequireAuth() {
  const auth = useAuth();

  useEffect(() => {
    if (!auth.isLoading && !auth.isAuthenticated && !auth.activeNavigator) {
      void auth.signinRedirect();
    }
  }, [auth]);

  if (!auth.isAuthenticated) {
    return (
      <Center h="100vh">
        <Loader />
      </Center>
    );
  }

  return <Outlet />;
}
