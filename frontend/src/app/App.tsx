import { useCallback, useEffect, useRef, useState } from "react";
import { ActivityDetailPage } from "../features/activities/ActivityDetail";
import { LessonsPage } from "../features/activities/ActivityTiles";
import { Checking, LoginScreen, SetupScreen, SignedOutScreen } from "../features/auth/AuthScreens";
import { ChoresPage } from "../features/chores/Chores";
import { HomePage } from "../features/dashboard/HomePage";
import { StoryWizard } from "../features/onboarding/StoryWizard";
import { ProfilePage } from "../features/profile/ProfilePage";
import { RewardsPage } from "../features/rewards/RewardsPage";
import { SettingsPage } from "../features/settings/SettingsPage";
import { WorldPage } from "../features/world/WorldPage";
import * as ep from "../shared/api/endpoints";
import { ToastProvider, useToast } from "../shared/ui/Toast";
import { errorText } from "../shared/ui/States";
import { AppShell, MENUS } from "./AppShell";
import { navigate, useRoute, type Route } from "./router";
import { SessionProvider, useMe, useSession } from "./session";
import { useTheme } from "./theme";
import { ONBOARDING_VERSION, TourContext } from "./tour";

export function App() {
  return (
    <ToastProvider>
      <SessionProvider>
        <Root />
      </SessionProvider>
    </ToastProvider>
  );
}

function Root() {
  useTheme(); // applies the theme on every screen, including login
  const { status, retry, signOut } = useSession();
  switch (status.kind) {
    case "checking":
      return <Checking onRetry={retry} />;
    case "setup":
      return <SetupScreen error={status.error} ready={status.ready} onRetry={retry} />;
    case "anonymous":
      return <LoginScreen expired={status.reason === "expired"} />;
    case "signed_out":
      return (
        <SignedOutScreen
          onSignIn={retry}
          warning={status.warning}
          onRetryLogout={status.retryable ? () => void signOut() : undefined}
        />
      );
    case "authenticated":
      return <AuthedApp />;
  }
}

function crumbFor(route: Route): string {
  if (route.page === "profile") return "Мой профиль";
  if (route.page === "activity") return "Занятие";
  return MENUS.find((m) => m[0] === route.page)?.[2] ?? "Мой день";
}

function AuthedApp() {
  const me = useMe();
  const { updateMe } = useSession();
  const toast = useToast();
  const route = useRoute();
  const [tourOpen, setTourOpen] = useState(false);
  const autoShown = useRef(false);

  // First run: show the wizard automatically once (until completed or skipped).
  useEffect(() => {
    if (!autoShown.current && me.onboarding_version < ONBOARDING_VERSION) {
      autoShown.current = true;
      setTourOpen(true);
    }
  }, [me.onboarding_version]);

  const openTour = useCallback(() => setTourOpen(true), []);

  async function closeTour({ completed, world }: { completed: boolean; world: string | null }) {
    setTourOpen(false);
    let current = me;
    try {
      if (me.onboarding_version < ONBOARDING_VERSION) {
        current = await ep.patchMe({ onboarding_version: ONBOARDING_VERSION });
        updateMe(current);
      }
      if (completed && world) {
        await ep.addWorld(world); // free and idempotent (200 when already owned)
        const res = await ep.setActiveWorld(world);
        updateMe({ ...current, active_world: res.active_world });
        navigate({ page: "world" });
      }
    } catch (e) {
      toast(errorText(e));
    }
  }

  const activeMenu: Route["page"] | null =
    route.page === "activity" ? "lessons" : route.page === "profile" ? null : route.page;

  return (
    <TourContext.Provider value={openTour}>
      <AppShell route={route} activeMenu={activeMenu} crumb={crumbFor(route)}>
        <Page route={route} />
      </AppShell>
      {tourOpen && <StoryWizard initialWorld={me.active_world} onClose={closeTour} />}
    </TourContext.Provider>
  );
}

function Page({ route }: { route: Route }) {
  switch (route.page) {
    case "home":
      return <HomePage />;
    case "lessons":
      return <LessonsPage />;
    case "walk":
      return <ActivityDetailPage walk />;
    case "activity":
      return <ActivityDetailPage id={route.id} />;
    case "chores":
      return <ChoresPage />;
    case "world":
      return <WorldPage />;
    case "rewards":
      return <RewardsPage />;
    case "settings":
      return <SettingsPage />;
    case "profile":
      return <ProfilePage />;
  }
}
