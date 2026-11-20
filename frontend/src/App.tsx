import { NavLink, Route, Routes } from "react-router";
import Toaster from "./components/layout/Toaster";
import AnalysisPage from "./pages/AnalysisPage";
import Dashboard from "./pages/Dashboard";
import ExplorerPage from "./pages/ExplorerPage";
import ImagesPage from "./pages/ImagesPage";
import JobsPage from "./pages/JobsPage";

const navItems = [
  { to: "/", label: "Oversikt" },
  { to: "/images", label: "Bilder" },
  { to: "/explorer", label: "Kart" },
  { to: "/analysis", label: "Analyse" },
  { to: "/jobs", label: "Jobber" },
];

export default function App() {
  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900 md:flex-row dark:bg-slate-950 dark:text-slate-100">
      <aside className="border-b border-slate-200 p-4 md:w-56 md:border-r md:border-b-0 dark:border-slate-800">
        <div className="mb-4 text-lg font-semibold">Satellite Object Detection</div>
        <nav aria-label="Hovedmeny" className="flex gap-2 md:flex-col">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end
              className={({ isActive }) =>
                `rounded px-3 py-2 text-sm ${
                  isActive
                    ? "bg-slate-200 font-medium dark:bg-slate-800"
                    : "hover:bg-slate-100 dark:hover:bg-slate-900"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="flex-1 p-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/images" element={<ImagesPage />} />
          <Route path="/explorer" element={<ExplorerPage />} />
          <Route path="/analysis" element={<AnalysisPage />} />
          <Route path="/jobs" element={<JobsPage />} />
        </Routes>
      </main>
      <Toaster />
    </div>
  );
}
