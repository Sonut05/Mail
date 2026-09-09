import React, { useState, useEffect } from 'react';
import { 
  X, MessageSquare, Clock, User, ChevronDown, ChevronUp, AlertCircle, 
  Paperclip, ArrowRight, CheckCircle2, ShieldAlert
} from 'lucide-react';
import { fetchThreadById } from '../services/api';

export default function ThreadViewModal({ threadId, onClose, onSelectEmail }) {
  const [threadData, setThreadData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [expandedMessages, setExpandedMessages] = useState({});

  useEffect(() => {
    if (!threadId) return;
    let isMounted = true;
    setLoading(true);
    setError(null);

    fetchThreadById(threadId)
      .then((res) => {
        if (!isMounted) return;
        if (res && res.thread) {
          setThreadData(res.thread);
          // Expand the latest message by default
          const msgs = res.thread.messages || [];
          if (msgs.length > 0) {
            setExpandedMessages({ [msgs[msgs.length - 1].id]: true });
          }
        } else {
          setError(res?.error || 'Failed to load conversation thread.');
        }
      })
      .catch((err) => {
        if (isMounted) setError(err.message || 'Error loading thread.');
      })
      .finally(() => {
        if (isMounted) setLoading(false);
      });

    return () => { isMounted = false; };
  }, [threadId]);

  const toggleMessage = (id) => {
    setExpandedMessages((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const getStatusBadge = (status) => {
    switch ((status || '').toUpperCase()) {
      case 'WAITING_FOR_USER':
        return <span className="badge badge-error"><AlertCircle size={13} className="mr-1 inline" /> Action Required</span>;
      case 'WAITING_FOR_OTHER':
        return <span className="badge badge-warning"><Clock size={13} className="mr-1 inline" /> Waiting on Reply</span>;
      case 'STALE':
        return <span className="badge badge-neutral"><ShieldAlert size={13} className="mr-1 inline" /> Stale (No Activity)</span>;
      case 'RESOLVED':
        return <span className="badge badge-success"><CheckCircle2 size={13} className="mr-1 inline" /> Resolved</span>;
      default:
        return <span className="badge badge-info"><MessageSquare size={13} className="mr-1 inline" /> Active</span>;
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="relative w-full max-w-3xl bg-[#131620]/95 border border-white/10 rounded-2xl shadow-2xl p-6 text-white overflow-hidden max-h-[90vh] flex flex-col">
        {/* Header */}
        <div className="flex items-start justify-between pb-4 border-b border-white/10">
          <div className="space-y-1 pr-6">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-xs uppercase tracking-wider text-white/50 font-semibold">Conversation</span>
              {threadData && getStatusBadge(threadData.status)}
            </div>
            <h2 className="text-xl font-bold text-white tracking-tight">
              {threadData ? threadData.subject : 'Loading Conversation...'}
            </h2>
            {threadData?.status_reason && (
              <p className="text-xs text-white/70 italic flex items-center gap-1">
                <span>Reason:</span> {threadData.status_reason}
              </p>
            )}
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-xl bg-white/5 hover:bg-white/10 text-white/70 hover:text-white transition-colors"
            title="Close"
          >
            <X size={20} />
          </button>
        </div>

        {/* Participants & Stats Bar */}
        {threadData && (
          <div className="py-3 px-4 my-3 bg-white/5 rounded-xl border border-white/5 flex flex-wrap items-center justify-between text-xs text-white/70 gap-2">
            <div className="flex items-center gap-2 flex-wrap">
              <User size={14} className="text-indigo-400" />
              <span className="font-medium text-white">Participants:</span>
              {(threadData.participants || []).map((p, idx) => (
                <span key={idx} className="bg-indigo-500/10 text-indigo-300 px-2 py-0.5 rounded-md border border-indigo-500/20">
                  {p.name || p.email}
                </span>
              ))}
            </div>
            <div className="flex items-center gap-3">
              <span>{threadData.message_count || 0} messages</span>
              {threadData.earliest_deadline && (
                <span className="text-amber-300">
                  Deadline: {new Date(threadData.earliest_deadline).toLocaleDateString()}
                </span>
              )}
            </div>
          </div>
        )}

        {/* Content Area */}
        <div className="flex-1 overflow-y-auto space-y-3 pr-1">
          {loading && (
            <div className="py-12 text-center text-white/50 animate-pulse">
              Loading conversation messages...
            </div>
          )}

          {error && (
            <div className="p-4 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm">
              {error}
            </div>
          )}

          {!loading && threadData?.messages && threadData.messages.map((msg, idx) => {
            const isExpanded = expandedMessages[msg.id] ?? false;
            return (
              <div
                key={msg.id || idx}
                className={`border rounded-xl transition-all duration-200 ${
                  isExpanded
                    ? 'bg-white/[0.04] border-white/15 shadow-md'
                    : 'bg-white/[0.02] border-white/5 hover:border-white/10'
                }`}
              >
                {/* Message Header bar */}
                <div
                  onClick={() => toggleMessage(msg.id)}
                  className="p-3.5 flex items-center justify-between cursor-pointer select-none"
                >
                  <div className="flex items-center gap-3 min-w-0">
                    <div className="w-8 h-8 rounded-full bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center font-bold text-xs text-white uppercase shadow-sm">
                      {(msg.from_address || '?')[0]}
                    </div>
                    <div className="truncate">
                      <div className="font-semibold text-sm text-white truncate">
                        {msg.from_address || 'Unknown'}
                      </div>
                      <div className="text-xs text-white/50 truncate">
                        To: {msg.to_address || 'Me'}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 text-xs text-white/60 shrink-0">
                    {msg.has_attachments && (
                      <span className="flex items-center gap-1 text-white/70" title="Has Attachments">
                        <Paperclip size={13} />
                      </span>
                    )}
                    {msg.ai_action_required && (
                      <span className="px-2 py-0.5 rounded bg-rose-500/20 text-rose-300 font-medium text-[11px] border border-rose-500/30">
                        Action
                      </span>
                    )}
                    <span>
                      {msg.received_at ? new Date(msg.received_at).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : ''}
                    </span>
                    {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                  </div>
                </div>

                {/* Expanded Message Content */}
                {isExpanded && (
                  <div className="px-4 pb-4 pt-1 border-t border-white/5 space-y-3">
                    {msg.ai_summary && (
                      <div className="p-2.5 rounded-lg bg-indigo-500/10 border border-indigo-500/20 text-xs text-indigo-200">
                        <span className="font-semibold text-indigo-300 mr-1">AI Summary:</span>
                        {msg.ai_summary}
                      </div>
                    )}

                    <div className="text-sm text-white/80 whitespace-pre-wrap font-sans leading-relaxed max-h-64 overflow-y-auto bg-black/20 p-3 rounded-lg border border-white/5">
                      {msg.body_text || msg.summary || '(No text content available)'}
                    </div>

                    <div className="flex items-center justify-end gap-2 pt-1">
                      {onSelectEmail && (
                        <button
                          onClick={() => {
                            onClose();
                            onSelectEmail(msg);
                          }}
                          className="px-3 py-1.5 rounded-lg bg-indigo-600/80 hover:bg-indigo-600 text-xs font-medium text-white flex items-center gap-1.5 transition-colors shadow-sm"
                        >
                          View Full Details <ArrowRight size={13} />
                        </button>
                      )}
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Footer */}
        <div className="pt-4 mt-3 border-t border-white/10 flex justify-end">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded-xl bg-white/10 hover:bg-white/15 text-sm font-medium text-white transition-colors"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
}
