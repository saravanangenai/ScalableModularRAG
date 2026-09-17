import { Center, Loader, Text } from "@mantine/core";
import { useAuth } from "react-oidc-context";

/**
 * OIDC redirect target. react-oidc-context's AuthProvider automatically exchanges the
 * code/state query params for tokens on mount (PKCE handled by oidc-client-ts) and then
 * calls onSigninCallback (AuthProvider.tsx), which navigates away from here — this page
 * just needs to render something sensible while that happens, and surface an error if it
 * fails.
 */
export function LoginCallback() {
  const auth = useAuth();

  if (auth.error) {
    return (
      <Center h="100vh">
        <Text c="red">Sign-in failed: {auth.error.message}</Text>
      </Center>
    );
  }

  return (
    <Center h="100vh">
      <Loader />
    </Center>
  );
}
