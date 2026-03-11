import { useState, useEffect, useCallback } from 'react';
import { Routes, Route, useNavigate, useLocation } from 'react-router-dom';
import NavBar from './components/NavBar';
import CommandPalette from './components/CommandPalette';
import Today from './pages/Today';
import Prep from './pages/Prep';
import Review from './pages/Review';
import Search from './pages/Search';
import ConversationDetail from './pages/ConversationDetail';
import Learning from './pages/Learning';
import SpeakerReview from './pages/SpeakerReview';
import BeliefReview from './pages/BeliefReview';
import Upload from './pages/Upload';
import { api } from './api';

export default function App() {
  const [commandPaletteOpen, setCommandPaletteOpen] = useState(false);
  const [badgeCounts, setBadgeCounts] = useState({});

  useEffect(() => {
    const fetchCounts = () => api.queueCounts().then(setBadgeCounts).catch(() => {});
    fetchCounts();
    const interval = setInterval(fetchCounts, 30000);
    return () => clearInterval(interval);
  }, []);
  const navigate = useNavigate();
  const location = useLocation();

  const handleKeyDown = useCallback((e) => {
    // Don't capture when typing in inputs
    const tag = e.target.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;

    if (e.key === '/') {
      e.preventDefault();
      setCommandPaletteOpen(true);
    } else if (e.key === 't' || e.key === 'T') {
      navigate('/');
    } else if (e.key === 'p' || e.key === 'P') {
      navigate('/prep');
    } else if (e.key === 'r' || e.key === 'R') {
      navigate('/review');
    } else if (e.key === 's' || e.key === 'S') {
      navigate('/search');
    } else if (e.key === 'l' || e.key === 'L') {
      navigate('/learning');
    } else if (e.key === 'Escape') {
      setCommandPaletteOpen(false);
    }
  }, [navigate]);

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [handleKeyDown]);

  return (
    <div className="min-h-screen bg-bg">
      <NavBar
        onCommandPalette={() => setCommandPaletteOpen(true)}
        badgeCounts={badgeCounts}
      />

      <main className="pt-14 px-4 md:px-8 max-w-6xl mx-auto">
        <Routes>
          <Route path="/" element={<Today />} />
          <Route path="/prep" element={<Prep />} />
          <Route path="/prep/:query" element={<Prep />} />
          <Route path="/review" element={<Review />} />
          <Route path="/review/beliefs" element={<BeliefReview />} />
          <Route path="/review/:id/speakers" element={<SpeakerReview />} />
          <Route path="/review/:id" element={<ConversationDetail />} />
          <Route path="/conversations/:id" element={<ConversationDetail />} />
          <Route path="/search" element={<Search />} />
          <Route path="/learning" element={<Learning />} />
          <Route path="/upload" element={<Upload />} />
        </Routes>
      </main>

      <CommandPalette
        open={commandPaletteOpen}
        onClose={() => setCommandPaletteOpen(false)}
        onNavigate={(path) => {
          navigate(path);
          setCommandPaletteOpen(false);
        }}
      />
    </div>
  );
}
