import { Link, NavLink, Route, Routes } from "react-router-dom";
import History from "./components/History";
import KitBoard from "./components/KitBoard";
import LiveView from "./components/LiveView";
import NewKitForm from "./components/NewKitForm";

function NavBar() {
  const link = ({ isActive }: { isActive: boolean }) =>
    `px-3 py-1.5 rounded-md text-sm transition ${
      isActive ? "bg-edge text-white" : "text-muted hover:text-slate-200"
    }`;
  return (
    <header className="border-b border-edge bg-panel/80 backdrop-blur sticky top-0 z-10">
      <div className="max-w-6xl mx-auto px-6 h-14 flex items-center gap-6">
        <Link to="/" className="flex items-center gap-2">
          <span className="font-display text-xl text-accent">StyleForge</span>
          <span className="text-xs text-muted hidden sm:inline">
            AI Brand Identity Studio
          </span>
        </Link>
        <nav className="flex items-center gap-1 ml-auto">
          <NavLink to="/" end className={link}>
            New Kit
          </NavLink>
          <NavLink to="/history" className={link}>
            History
          </NavLink>
        </nav>
      </div>
    </header>
  );
}

export default function App() {
  return (
    <div className="min-h-full">
      <NavBar />
      <main className="max-w-6xl mx-auto px-6 py-8">
        <Routes>
          <Route path="/" element={<NewKitForm />} />
          <Route path="/run/:runId" element={<LiveView />} />
          <Route path="/kit/:runId" element={<KitBoard />} />
          <Route path="/history" element={<History />} />
        </Routes>
      </main>
    </div>
  );
}
