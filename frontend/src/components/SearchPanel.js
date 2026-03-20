import React, { useState, useEffect, useRef } from 'react';
import CourseDetail from './CourseDetail';

function SearchPanel({ onCourseClick, selectedCourse, onBackToResults }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef(null);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);

    if (!query.trim()) {
      setResults([]);
      return;
    }

    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const res = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
        if (res.ok) setResults(await res.json());
      } catch {
        // ignore
      }
      setLoading(false);
    }, 300);

    return () => clearTimeout(debounceRef.current);
  }, [query]);

  return (
    <section className="w-[40%] flex flex-col border-r border-white/5 bg-[#1A1A2E]">
      {/* Search Header with Branding */}
      <div className="p-6 pb-2 space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3 text-xl font-bold text-[#F3F4F6]">
            <div className="w-8 h-8 rounded-full bg-[#FF3B30] flex items-center justify-center text-white text-sm font-black ring-2 ring-white/10">N</div>
            <span className="font-headline tracking-tight">NEU Insights</span>
          </div>
          <div className="px-2 py-0.5 rounded-full border border-[#FF3B30]/30 bg-[#FF3B30]/10 text-[#FF3B30] text-[9px] font-black tracking-widest uppercase">
            AI-POWERED
          </div>
        </div>

        <div className="relative group focus-red-glow transition-all duration-300 rounded-xl border border-transparent">
          <span className="material-symbols-outlined absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 group-focus-within:text-[#FF3B30] transition-colors text-[20px]">search</span>
          <input
            className="w-full h-12 pl-9 pr-4 glass-input border-none rounded-xl text-[#F3F4F6] placeholder:text-gray-600 focus:ring-1 focus:ring-[#FF3B30]/20 transition-all outline-none"
            placeholder="Search courses..."
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              if (selectedCourse) onBackToResults();
            }}
          />
        </div>
      </div>

      {/* Scrollable List & Details */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-4">
        {selectedCourse ? (
          <CourseDetail course={selectedCourse} onBack={onBackToResults} />
        ) : !query.trim() ? (
          <div className="flex flex-col items-center justify-center h-full text-center text-gray-500/50 -mt-8">
            <span className="material-symbols-outlined text-[48px] mb-4 opacity-30">menu_book</span>
            <p className="text-sm leading-relaxed">
              Search for courses by title or code,<br />e.g. "algorithms" or "CS 3000"
            </p>
          </div>
        ) : loading ? (
          <div className="flex flex-col items-center justify-center h-full text-center text-gray-500/60">
            <p className="text-sm">Searching...</p>
          </div>
        ) : results.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center text-gray-500/60">
            <p className="text-sm">No courses found for "{query}"</p>
          </div>
        ) : (
          <div className="space-y-3">
            <label className="text-[11px] uppercase tracking-widest text-gray-500 font-bold px-1">Top Matches</label>
            {results.map((course) => (
              <button
                key={`${course.department_code}-${course.number}`}
                className="w-full text-left glass-card p-4 rounded-xl flex justify-between items-center transition-all duration-300 hover:bg-white/5 hover:border-l-[3px] hover:border-l-[#FF3B30] cursor-pointer border-l-[3px] border-l-transparent"
                onClick={() => onCourseClick(course)}
              >
                <div>
                  <div className="font-bold text-[#F3F4F6]">
                    {course.department_code.toUpperCase()} {course.number}
                  </div>
                  <div className="text-sm text-gray-400">{course.title}</div>
                </div>
                <div className="text-[10px] uppercase tracking-tighter text-gray-500 font-bold bg-white/5 px-2 py-1 rounded flex-shrink-0 ml-3">
                  {course.credits} Credits
                </div>
              </button>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

export default SearchPanel;
