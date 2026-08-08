import * as Dialog from "@radix-ui/react-dialog";
import {
  Bot,
  GitBranch,
  Home,
  ListFilter,
  Menu,
  Moon,
  Play,
  Search,
  Settings,
  SlidersHorizontal,
  Sun,
  X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

const navigation = [
  ["/", "Home", Home],
  ["/assistant", "Assistant", Bot],
  ["/opportunities", "Opportunities", ListFilter],
  ["/repositories", "Repositories", GitBranch],
  ["/preferences", "Preferences", SlidersHorizontal],
  ["/runs", "Runs", Play],
  ["/settings", "Settings", Settings],
] as const;

export function AppShell() {
  const navigate = useNavigate();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen(true);
      }
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, []);

  return (
    <div className="app-shell">
      <aside className="sidebar" aria-label="Primary navigation">
        <div className="brand"><span className="brand-mark">R</span><span>Radar</span></div>
        <nav>
          {navigation.map(([path, label, Icon]) => (
            <NavLink key={path} to={path} end={path === "/"}>
              <Icon aria-hidden="true" size={17} /><span>{label}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-actions">
          <button className="ghost-button" onClick={() => setPaletteOpen(true)} aria-label="Open command palette">
            <Menu size={16} aria-hidden="true" /><span>Commands</span><kbd>⌘K</kbd>
          </button>
          <button className="ghost-button" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}>
            {theme === "dark" ? <Sun size={16} aria-hidden="true" /> : <Moon size={16} aria-hidden="true" />}
            <span>{theme === "dark" ? "Light theme" : "Dark theme"}</span>
          </button>
        </div>
      </aside>
      <main id="main-content"><Outlet /></main>
      <Dialog.Root open={paletteOpen} onOpenChange={setPaletteOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="command-dialog" aria-describedby={undefined}>
            <Dialog.Title>Go to</Dialog.Title>
            <Dialog.Close className="icon-button" aria-label="Close command palette"><X size={18} /></Dialog.Close>
            <div className="command-list">
              {navigation.map(([path, label, Icon]) => (
                <button key={path} onClick={() => { navigate(path); setPaletteOpen(false); }}>
                  <Icon size={16} aria-hidden="true" />{label}
                </button>
              ))}
            </div>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </div>
  );
}

export function PageHeader({ eyebrow, title, children }: { eyebrow?: string; title: string; children?: React.ReactNode }) {
  return <header className="page-header"><div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h1>{title}</h1></div>{children}</header>;
}

export function Placeholder({ title, description }: { title: string; description: string }) {
  return <section className="empty-state"><Search aria-hidden="true" /><h2>{title}</h2><p>{description}</p></section>;
}
