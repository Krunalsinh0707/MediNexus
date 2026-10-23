import React, { useState, useEffect } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Bot, X, Minus, History as HistoryIcon, Plus } from 'lucide-react';
import { useAuth } from '../../context/AuthContext';
import clinicalChatService from '../../services/clinicalChatService';
import ChatWindow from './ChatWindow';
import ChatInput from './ChatInput';
import SuggestedQuestions from './SuggestedQuestions';
import ChatHistoryPanel from './ChatHistoryPanel';
import { clinicalWriteError } from '../../pages/clinicalWriteErrors';

const ChatbotDrawer = () => {
  const { user } = useAuth();
  const [isOpen, setIsOpen] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  
  const [conversations, setConversations] = useState([]);
  const [activeConvId, setActiveConvId] = useState(null);
  const [messages, setMessages] = useState([
    {
      sender: 'assistant',
      text: "Hello! I'm HealthBot. How can I help you today?",
      time: "Just now"
    }
  ]);
  const [inputMsg, setInputMsg] = useState('');
  const [loading, setLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');

  // Fetch consultation sessions when drawer opens
  useEffect(() => {
    if (user && isOpen) {
      fetchConversations();
    }
  }, [user, isOpen]);

  const fetchConversations = async () => {
    try {
      const data = await clinicalChatService.getMyConversations();
      setConversations(data || []);
      // If no active conversation yet and conversations exist, select the latest
      if (!activeConvId && data && data.length > 0) {
        // Keep activeConvId null initially unless user selects it or sends message
      }
    } catch (err) {
      console.error("Failed to load consultations", err);
    }
  };

  const fetchSessionMessages = async (convId) => {
    setActiveConvId(convId);
    setLoading(true);
    try {
      const msgs = await clinicalChatService.getConversationMessages(convId);
      if (msgs && msgs.length > 0) {
        setMessages(msgs.map(m => ({
          sender: m.sender_type === 'patient' ? 'user' : 'assistant',
          text: m.body,
          time: new Date(m.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        })));
      } else {
        setMessages([{
          sender: 'assistant',
          text: "Hello! I'm HealthBot. How can I help you today?",
          time: "Just now"
        }]);
      }
    } catch (err) {
      console.error("Failed to fetch messages", err);
    } finally {
      setLoading(false);
    }
  };

  const handleNewSession = async () => {
    try {
      const newConv = await clinicalChatService.createConversation({ title: "Health Consultation" });
      setActiveConvId(newConv.id);
      setMessages([{
        sender: 'assistant',
        text: "Hello! I'm HealthBot. How can I help you today?",
        time: "Just now"
      }]);
      fetchConversations();
    } catch (err) {
      console.error("Failed to create new consultation session", err);
    }
  };

  const handleDeleteSession = async (convId) => {
    setHistoryError('');
    try {
      await clinicalChatService.deleteConversation(convId);
      if (activeConvId === convId) {
        setActiveConvId(null);
        setMessages([{
          sender: 'assistant',
          text: "Hello! I'm HealthBot. How can I help you today?",
          time: "Just now"
        }]);
      }
      fetchConversations();
    } catch (err) {
      console.error("Failed to delete consultation session", err);
      setHistoryError(clinicalWriteError(err, 'hide'));
    }
  };

  const handleSend = async (customText) => {
    const query = customText || inputMsg;
    if (!query.trim()) return;

    const userMessage = { 
      sender: 'user', 
      text: query, 
      time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) 
    };
    setMessages(prev => [...prev, userMessage]);
    if (!customText) setInputMsg('');
    setLoading(true);

    try {
      if (!activeConvId) {
        const title = query.length > 35 ? query.substring(0, 35) + "..." : query;
        const newConv = await clinicalChatService.createConversation({
          title,
          initial_message: query
        });
        setActiveConvId(newConv.id);
        await fetchConversations();
        const msgs = await clinicalChatService.getConversationMessages(newConv.id);
        if (msgs && msgs.length > 0) {
          setMessages(msgs.map(m => ({
            sender: m.sender_type === 'patient' ? 'user' : 'assistant',
            text: m.body,
            time: new Date(m.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
          })));
        }
        return;
      }

      const response = await clinicalChatService.sendMessage(activeConvId, query);
      const botText = response.assistant_message?.body || "I have received your message.";
      const botMessage = {
        sender: 'assistant',
        text: botText,
        time: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
        clarification_options: response.clarification_options,
        workflow_state: response.workflow_state
      };
      setMessages(prev => [...prev, botMessage]);
    } catch (err) {
      console.error("Chatbot request error:", err.response?.data || err.message);
      const errorMsg = "I'm having trouble processing that request right now. Please try again.";
      setMessages(prev => [...prev, {
        sender: 'assistant',
        text: errorMsg,
        time: "Just now"
      }]);
    } finally {
      setLoading(false);
    }
  };

  if (!user) return null;

  return (
    <div className="fixed bottom-6 right-6 z-50 flex flex-col items-end pointer-events-auto">
      {/* FLOATING CHAT PANEL */}
      <AnimatePresence>
        {isOpen && (
          <motion.div
            initial={{ opacity: 0, y: 30, scale: 0.95 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 30, scale: 0.95 }}
            transition={{ duration: 0.2 }}
            className="mb-3 w-[calc(100vw-2rem)] sm:w-[420px] h-[580px] max-h-[calc(100vh-120px)] bg-white rounded-3xl shadow-2xl border border-slate-200 flex flex-col overflow-hidden"
          >
            {/* PANEL HEADER */}
            <div className="bg-slate-900 px-4 py-3 text-white flex items-center justify-between z-10 shrink-0">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-teal-500/10 border border-teal-500/30 flex items-center justify-center text-[#0F9D8A]">
                  <Bot size={22} />
                </div>
                <div>
                  <h3 className="text-sm font-black tracking-tight text-white">HealthBot</h3>
                  <div className="flex items-center gap-1.5 text-[11px] text-teal-400 font-semibold">
                    <div className="w-1.5 h-1.5 bg-emerald-400 rounded-full animate-pulse" />
                    <span>Hospital Assistant</span>
                  </div>
                </div>
              </div>

              <div className="flex items-center gap-1">
                <button
                  onClick={() => setShowHistory(!showHistory)}
                  className="p-1.5 text-slate-400 hover:text-white rounded-lg transition-colors"
                  title="Chat Sessions"
                  aria-label="Chat Sessions"
                >
                  <HistoryIcon size={18} />
                </button>
                <button
                  onClick={handleNewSession}
                  className="p-1.5 text-slate-400 hover:text-white rounded-lg transition-colors"
                  title="New Consultation"
                  aria-label="New Consultation"
                >
                  <Plus size={18} />
                </button>
                <button
                  onClick={() => setIsOpen(false)}
                  className="p-1.5 text-slate-400 hover:text-white rounded-lg transition-colors"
                  title="Minimize"
                  aria-label="Minimize"
                >
                  <Minus size={18} />
                </button>
                <button 
                  onClick={() => setIsOpen(false)}
                  className="p-1.5 text-slate-400 hover:text-white rounded-lg transition-colors"
                  title="Close"
                  aria-label="Close"
                >
                  <X size={18} />
                </button>
              </div>
            </div>

            {/* SAVED HISTORY DRAWER SLIDE-OVER */}
            {showHistory && (
              <ChatHistoryPanel
                conversations={conversations}
                activeId={activeConvId}
                onSelectConv={fetchSessionMessages}
                onNewConv={handleNewSession}
                onDeleteConv={handleDeleteSession}
                error={historyError}
                onClose={() => setShowHistory(false)}
              />
            )}

            {/* CHAT MESSAGES WINDOW */}
            <ChatWindow messages={messages} loading={loading} onSelectOption={handleSend} />

            {/* SUGGESTED QUESTIONS */}
            <SuggestedQuestions onSelectQuestion={handleSend} />

            {/* INPUT FIELD */}
            <ChatInput 
              inputMsg={inputMsg} 
              setInputMsg={setInputMsg} 
              onSend={handleSend} 
              loading={loading} 
            />
          </motion.div>
        )}
      </AnimatePresence>

      {/* FLOATING ROUND HEALTHBOT LAUNCHER BUTTON */}
      <div className="flex flex-col items-center">
        <motion.button
          whileHover={{ scale: 1.08 }}
          whileTap={{ scale: 0.94 }}
          onClick={() => setIsOpen(!isOpen)}
          aria-label={isOpen ? "Minimize HealthBot" : "Open HealthBot Assistant"}
          title={isOpen ? "Minimize HealthBot" : "Open HealthBot Assistant"}
          className={`w-14 h-14 rounded-full shadow-2xl flex items-center justify-center transition-all border-2 ${
            isOpen 
              ? 'bg-slate-900 border-teal-400 text-teal-400 shadow-teal-500/20' 
              : 'bg-gradient-to-br from-slate-900 via-slate-800 to-teal-950 border-teal-500/50 text-teal-400 hover:border-teal-400 shadow-slate-900/40 hover:shadow-teal-500/30'
          }`}
        >
          <div className="relative flex items-center justify-center">
            <Bot size={26} className="text-[#0F9D8A]" />
            <span className="absolute -top-1 -right-1 w-2.5 h-2.5 bg-emerald-500 rounded-full animate-ping" />
            <span className="absolute -top-1 -right-1 w-2.5 h-2.5 bg-emerald-500 rounded-full" />
          </div>
        </motion.button>
        <span className="text-[10px] font-bold text-slate-700 bg-white/95 shadow-sm border border-slate-200/80 px-2 py-0.5 rounded-full mt-1.5 select-none pointer-events-none">
          HealthBot
        </span>
      </div>
    </div>
  );
};

export default ChatbotDrawer;
