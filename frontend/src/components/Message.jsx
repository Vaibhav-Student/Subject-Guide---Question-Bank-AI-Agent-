import { marked } from 'marked';
import { useMemo, useState } from 'react';
import { BookOpen, BarChart3, FileText, TrendingUp, ClipboardList, Copy, Check, Edit2, Trash2 } from './Icons';

marked.setOptions({ breaks: true, gfm: true });



function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

export default function Message({ role, content, intent, sources, onEdit, onDelete }) {
  const [copied, setCopied] = useState(false);
  const [isEditing, setIsEditing] = useState(false);
  const [editContent, setEditContent] = useState(content);

  const parsedContent = useMemo(() => {
    return role === 'assistant' ? marked.parse(content) : escapeHtml(content);
  }, [content, role]);

  const handleCopy = () => {
    navigator.clipboard.writeText(content);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleSaveEdit = () => {
    setIsEditing(false);
    if (editContent.trim() !== content && editContent.trim() !== '') {
      if (onEdit) onEdit(editContent.trim());
    } else {
      setEditContent(content);
    }
  };

  const handleCancelEdit = () => {
    setIsEditing(false);
    setEditContent(content);
  };

  return (
    <div className={`msg ${role}`}>
      <div className="msg-bubble">
        {role === 'user' && !isEditing && (
          <div className="msg-actions">
            <button className="msg-action-btn" onClick={() => setIsEditing(true)} title="Edit"><Edit2 size={13} /></button>
            <button className="msg-action-btn delete" onClick={onDelete} title="Delete"><Trash2 size={13} /></button>
          </div>
        )}

        {role === 'assistant' && (
          <div className="msg-header" style={{ justifyContent: 'flex-start', padding: '0 4px 4px' }}>
            <button className="msg-copy-btn" onClick={handleCopy} title="Copy message" style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
              {copied ? <Check size={14} /> : <Copy size={14} />}
              <span style={{ fontSize: '0.7rem', fontWeight: 500 }}>{copied ? 'Copied' : 'Copy'}</span>
            </button>
          </div>
        )}

        {isEditing ? (
          <div className="msg-edit-mode">
            <textarea
              value={editContent}
              onChange={e => setEditContent(e.target.value)}
              className="msg-edit-textarea"
              rows={Math.max(2, editContent.split('\n').length)}
              autoFocus
            />
            <div className="msg-edit-actions">
              <button className="btn-save btn-primary" onClick={handleSaveEdit}>Save & Submit</button>
              <button className="btn-cancel btn-secondary" onClick={handleCancelEdit}>Cancel</button>
            </div>
          </div>
        ) : (
          <div className="msg-body" dangerouslySetInnerHTML={{ __html: parsedContent }} />
        )}
        {sources && sources.length > 0 && (
          <div className="msg-sources">
            {sources.map((s, i) => (
              <span key={i} className="msg-source-tag">
                <FileText size={11} /> {s.name}{s.page ? ` (p.${s.page})` : ''}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export function LoadingMessage() {
  return (
    <div className="msg assistant">
      <div className="msg-bubble">
        <div className="typing-indicator">
          <span /><span /><span />
        </div>
      </div>
    </div>
  );
}
