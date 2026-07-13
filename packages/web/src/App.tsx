import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { Sidebar } from './components/Layout/Sidebar';
import { Header } from './components/Layout/Header';
import { Footer } from './components/Layout/Footer';
import { Dashboard } from './pages/Dashboard';
import { Repos } from './pages/Repos';
import { RepoDetail } from './pages/RepoDetail';
import { Search } from './pages/Search';
import { Benchmark } from './pages/Benchmark';
import { Settings } from './pages/Settings';
import { Monitor } from './pages/Monitor';
import { useStore } from './store';
import { clsx } from 'clsx';

function App() {
  const { sidebarOpen, settings } = useStore();

  return (
    <Router>
      <div className={clsx('min-h-screen bg-slate-50 dark:bg-slate-900 transition-colors')}>
        <Sidebar />
        <div
          className={clsx(
            'transition-all duration-300',
            sidebarOpen ? 'ml-64' : 'ml-16'
          )}
        >
          <Header />
          <main className="p-6">
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/repos" element={<Repos />} />
              <Route path="/repos/:id" element={<RepoDetail />} />
              <Route path="/search" element={<Search />} />
              <Route path="/benchmark" element={<Benchmark />} />
              <Route path="/settings" element={<Settings />} />
              <Route path="/monitor" element={<Monitor />} />
            </Routes>
          </main>
          <Footer />
        </div>
      </div>
    </Router>
  );
}

export default App;
