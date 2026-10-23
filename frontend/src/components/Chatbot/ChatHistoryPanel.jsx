import React from 'react';
import { Plus, MessageSquare, Archive, X } from 'lucide-react';

const ChatHistoryPanel = ({ conversations, activeId, onSelectConv, onNewConv, onDeleteConv, onClose, error }) => {
  return (
    <div className="absolute inset-0 bg-slate-900/95 backdrop-blur-md z-20 text-white p-4 flex flex-col">
      <div className="flex items-center justify-between pb-4 border-b border-slate-800">
        <h3 className="text-sm font-black uppercase tracking-wider text-teal-400">Saved Chat Sessions</h3>
        <button onClick={onClose} className="p-1 text-slate-400 hover:text-white rounded-lg">
          <X size={18} />
        </button>
      </div>

      {error && <p role="alert" className="mt-3 rounded-lg bg-rose-900/40 p-2 text-xs text-rose-100">{error}</p>}

      <div className="mt-4">
        <button
          onClick={() => { onNewConv(); onClose(); }}
          className="w-full bg-[#0F9D8A] hover:bg-teal-600 text-white py-2.5 px-4 rounded-xl text-xs font-black uppercase tracking-wider flex items-center justify-center gap-2 transition-all shadow-lg shadow-teal-500/20"
        >
          <Plus size={16} /> New Chat Session
        </button>
      </div>

      <div className="flex-1 mt-4 space-y-2 overflow-y-auto custom-scrollbar">
        {conversations.map((conv) => (
          <div
            key={conv.id}
            onClick={() => { onSelectConv(conv.id); onClose(); }}
            className={`p-3 rounded-xl cursor-pointer flex items-center justify-between border transition-all ${conv.id === activeId ? 'bg-teal-500/20 border-teal-500/50 text-teal-300' : 'bg-slate-800/60 border-slate-700/50 text-slate-300 hover:bg-slate-800'}`}
          >
            <div className="flex items-center gap-2.5 truncate">
              <MessageSquare size={14} className="shrink-0 text-teal-400" />
              <span className="text-xs font-bold truncate">{conv.title || 'Conversation'}</span>
            </div>
            {conv.status === 'RESOLVED' && <button
              onClick={(e) => {
                e.stopPropagation();
                onDeleteConv(conv.id);
              }}
              className="text-slate-500 hover:text-rose-400 p-1 transition-colors"
              title="Hide resolved chat; clinical history is retained"
              aria-label="Hide resolved chat"
            >
              <Archive size={14} />
            </button>}
          </div>
        ))}

        {conversations.length === 0 && (
          <p className="text-xs text-slate-500 text-center py-8">No saved chat sessions.</p>
        )}
      </div>
    </div>
  );
};

export default ChatHistoryPanel;
