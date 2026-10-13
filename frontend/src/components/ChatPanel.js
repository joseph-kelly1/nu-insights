import React, { useState, useRef, useEffect } from 'react';
import ReactMarkdown from 'react-markdown';
import { PROVIDERS } from './AISettings';

function ChatPanel({ messages, onSend, onNewChat, aiSettings }) {
  const [input, setInput] = useState('');
  const messagesEndRef = useRef(null);
  const isThinking = messages.some((m) => m.role === 'system' && m.content === 'Thinking...');

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  const handleSubmit = (e) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || isThinking) return;
    setInput('');
    onSend(text);
  };

  return (
    <section className="w-[60%] flex flex-col relative bg-[#1A1A2E]">
      {/* Chat Header */}
      <div className="p-6 border-b border-white/5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded bg-[#FF3B30]/20 flex items-center justify-center">
            <span className="material-symbols-outlined text-[14px] text-[#FF3B30]" style={{ fontVariationSettings: "'FILL' 1" }}>auto_awesome</span>
          </div>
        </div>
        <button
          className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-white/5 hover:bg-white/10 text-[11px] font-bold text-gray-300 transition-colors border border-white/5"
          onClick={onNewChat}
        >
          <span className="material-symbols-outlined text-[16px]">add</span>
          New Chat
        </button>
      </div>
      {aiSettings}

      {/* Chat Messages */}
      <div className="flex-1 overflow-y-auto custom-scrollbar p-8 space-y-8 pb-32">
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-center text-gray-500/50 -mt-16">
            <span className="material-symbols-outlined text-[48px] mb-4 opacity-30" style={{ fontVariationSettings: "'FILL' 1" }}>chat_bubble</span>
            <p className="text-sm leading-relaxed">
              Ask about any course by typing its code<br />
              (e.g. "CS 3000") or click a course from search
            </p>
          </div>
        ) : (
          messages.map((msg, i) => {
            if (msg.role === 'user') {
              return (
                <div key={i} className="flex flex-col items-end w-full">
                  <div className="max-w-[70%] bg-[#FF3B30]/10 border border-[#FF3B30]/20 p-4 rounded-2xl rounded-tr-none text-sm text-[#F3F4F6] leading-relaxed">
                    {msg.content}
                  </div>
                </div>
              );
            }

            if (msg.role === 'system' && msg.content === 'Thinking...') {
              return (
                <div key={i} className="flex justify-center">
                  <span className="text-sm text-gray-500 thinking-dots">Thinking</span>
                </div>
              );
            }

            if (msg.role === 'system') {
              return (
                <div key={i} className="flex justify-center">
                  <span className="text-sm text-gray-500 text-center">{msg.content}</span>
                </div>
              );
            }

            // Assistant message
            return (
              <div key={i} className="flex flex-col items-start max-w-[90%] group/card">
                <div className="glass-card p-6 rounded-2xl border border-white/5 relative">
                  <button className="absolute top-4 right-4 text-gray-500 hover:text-white transition-colors opacity-0 group-hover/card:opacity-100">
                    <span className="material-symbols-outlined text-[18px]">content_copy</span>
                  </button>
                  <div className="prose-chat text-[14px] text-gray-300 leading-relaxed font-body">
                    <ReactMarkdown
                      components={{
                        h1: ({ children }) => <h3 className="text-sm font-bold text-[#F3F4F6] mt-4 mb-2 first:mt-0">{children}</h3>,
                        h2: ({ children }) => <h3 className="text-sm font-bold text-[#F3F4F6] mt-4 mb-2 first:mt-0">{children}</h3>,
                        h3: ({ children }) => <h3 className="text-sm font-bold text-[#F3F4F6] mt-4 mb-2 first:mt-0">{children}</h3>,
                        p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
                        ul: ({ children }) => <ul className="my-1 pl-5 space-y-1">{children}</ul>,
                        ol: ({ children }) => <ol className="my-1 pl-5 space-y-1">{children}</ol>,
                        li: ({ children }) => (
                          <li className="flex items-start gap-2">
                            <span className="w-1 h-1 rounded-full bg-[#FF3B30]/60 mt-2 flex-shrink-0"></span>
                            <span>{children}</span>
                          </li>
                        ),
                        strong: ({ children }) => <strong className="text-white font-semibold">{children}</strong>,
                        code: ({ children }) => (
                          <code className="bg-white/[0.06] px-1.5 py-0.5 rounded text-[13px] border border-white/10">{children}</code>
                        ),
                      }}
                    >
                      {msg.content}
                    </ReactMarkdown>
                  </div>
                  {msg.provider && (
                    <p className="mt-4 text-[11px] text-gray-500">{`via ${PROVIDERS[msg.provider].name} · ${msg.model}`}</p>
                  )}
                </div>
              </div>
            );
          })
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Chat Input Bar */}
      <div className="absolute bottom-0 w-full p-6 bg-gradient-to-t from-[#1A1A2E] via-[#1A1A2E]/90 to-transparent">
        <form onSubmit={handleSubmit} className="glass-card p-2 rounded-2xl flex items-center gap-2 border border-white/5 shadow-xl">
          <input
            className="flex-1 h-11 bg-transparent border-none text-sm text-[#F3F4F6] placeholder:text-gray-500/50 px-4 focus:ring-0 outline-none"
            placeholder="Type a course code or question..."
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={isThinking}
          />
          <button
            type="submit"
            disabled={!input.trim() || isThinking}
            className="bg-[#FF3B30] hover:bg-[#CC2F26] disabled:opacity-40 disabled:cursor-default text-white w-11 h-11 rounded-xl flex items-center justify-center transition-all duration-300 shadow-[0_0_20px_rgba(255,59,48,0.2)] hover:shadow-[0_0_30px_rgba(255,59,48,0.4)]"
          >
            <span className="material-symbols-outlined text-lg" style={{ fontVariationSettings: "'FILL' 1" }}>arrow_upward</span>
          </button>
        </form>
      </div>
    </section>
  );
}

export default ChatPanel;
