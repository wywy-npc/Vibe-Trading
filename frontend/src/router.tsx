import { Suspense, lazy, type ComponentType } from "react";
import { createBrowserRouter } from "react-router-dom";
import { Layout } from "@/components/layout/Layout";

const Home = lazy(() => import("@/pages/Home").then((m) => ({ default: m.Home })));
const Agent = lazy(() => import("@/pages/Agent").then((m) => ({ default: m.Agent })));
const RunDetail = lazy(() =>
  import("@/pages/RunDetail").then((m) => ({ default: m.RunDetail })),
);
const Compare = lazy(() =>
  import("@/pages/Compare").then((m) => ({ default: m.Compare })),
);
const Settings = lazy(() =>
  import("@/pages/Settings").then((m) => ({ default: m.Settings })),
);
const Correlation = lazy(() =>
  import("@/pages/Correlation").then((m) => ({ default: m.Correlation })),
);

// Office pages
const Floor    = lazy(() => import("@/pages/office/Floor").then((m)    => ({ default: m.Floor })));
const Inbox    = lazy(() => import("@/pages/office/Inbox").then((m)    => ({ default: m.Inbox })));
const Book     = lazy(() => import("@/pages/office/Book").then((m)     => ({ default: m.Book })));
const Mandates = lazy(() => import("@/pages/office/Mandates").then((m) => ({ default: m.Mandates })));
const Agents   = lazy(() => import("@/pages/office/Agents").then((m)   => ({ default: m.Agents })));
const Ledger   = lazy(() => import("@/pages/office/Ledger").then((m)   => ({ default: m.Ledger })));

function PageLoader() {
  return (
    <div className="flex h-[60vh] items-center justify-center text-muted-foreground">
      Loading…
    </div>
  );
}

function wrap(Component: ComponentType) {
  return (
    <Suspense fallback={<PageLoader />}>
      <Component />
    </Suspense>
  );
}

export const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { path: "/", element: wrap(Floor) },
      { path: "/office/floor", element: wrap(Floor) },
      { path: "/office/inbox", element: wrap(Inbox) },
      { path: "/office/book", element: wrap(Book) },
      { path: "/office/mandates", element: wrap(Mandates) },
      { path: "/office/agents",   element: wrap(Agents) },
      { path: "/office/ledger",   element: wrap(Ledger) },
      { path: "/agent", element: wrap(Agent) },
      { path: "/research", element: wrap(Home) },
      { path: "/settings", element: wrap(Settings) },
      { path: "/runs/:runId", element: wrap(RunDetail) },
      { path: "/compare", element: wrap(Compare) },
      { path: "/correlation", element: wrap(Correlation) },
    ],
  },
]);
