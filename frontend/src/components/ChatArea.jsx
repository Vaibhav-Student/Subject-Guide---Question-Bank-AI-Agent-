import { useState, useRef, useEffect, useMemo } from 'react';
import Message, { LoadingMessage } from './Message';
import { Menu, Send, BookOpen, BarChart3, FileText, TrendingUp, ClipboardList, Sparkles, Sun, Moon, X, UploadCloud, Plus, Settings, Key, Folder } from './Icons';
import { AI_TOOLS, getDefaultModel } from '../config/toolsData';
import { uploadFile, deleteDocument } from '../api';
import { UploadEngine, UploadStatus, isSmallFile, formatBytes } from '../uploadEngine';
import ToolSelector from './ToolSelector';
import ModelSelector from './ModelSelector';
import ApiKeyInput from './ApiKeyInput';
import { checkUnsupportedFeature } from '../featureGuard';

const DEFAULT_CHIPS = [
  { label: 'Explain Topic', icon: <BookOpen size={16} />, query: 'Explain ' },
  { label: 'Compare', icon: <BarChart3 size={16} />, query: 'Compare ' },
  { label: 'Solve Question', icon: <FileText size={16} />, query: 'Solve: ' },
  { label: 'Study Plan', icon: <TrendingUp size={16} />, query: 'Create a study roadmap for ' },
  { label: 'Summarize', icon: <ClipboardList size={16} />, query: 'Summarize ' },
];

const ALLOWED_EXTENSIONS = [
  'pdf', 'docx', 'doc', 'pptx', 'ppt', 'xlsx', 'xls', 'txt', 'md',
  'jpg', 'jpeg', 'png', 'webp', 'svg', 'mp4', 'webm', 'mov', 'avi', 'mkv'
];

const VIDEO_MAX_DURATION = 600; // 10 minutes in seconds

export default function ChatArea({
  messages,
  setMessages,
  showWelcome,
  setShowWelcome,
  onOpenSidebar,
  showNotification,
  selectedToolId,
  setSelectedToolId,
  selectedModelId,
  setSelectedModelId,
  theme,
  toggleTheme,
  onDocumentsChange,
  documents = [],
  totalChunks = 0,
  onToggleSidebar,
  sidebarOpen
}) {
  const [query, setQuery] = useState('');
  const [selectedChip, setSelectedChip] = useState(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [status, setStatus] = useState('');
  const [customChips, setCustomChips] = useState([]);
  const [showAddChip, setShowAddChip] = useState(false);
  const [newChipLabel, setNewChipLabel] = useState('');
  const [newChipQuery, setNewChipQuery] = useState('');
  const messagesEndRef = useRef(null);
  const textareaRef = useRef(null);
  const fileInputRef = useRef(null);
  const [uploadQueue, setUploadQueue] = useState([]);
  const [showSettings, setShowSettings] = useState(false);
  const [showUploadMenu, setShowUploadMenu] = useState(false);
  const folderInputRef = useRef(null);

  const engine = useMemo(() => new UploadEngine({ chunkSize: 2 * 1024 * 1024 }), []);

  useEffect(() => {
    const saved = localStorage.getItem('custom_chips');
    if (saved) {
      try {
        setCustomChips(JSON.parse(saved));
      } catch (e) {
        console.error('Failed to parse custom chips', e);
      }
    }
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isGenerating]);

  const allChips = useMemo(() => {
    return [...DEFAULT_CHIPS, ...customChips.map(c => ({
      ...c,
      icon: <Sparkles size={16} />,
      isCustom: true
    }))];
  }, [customChips]);

  function updateQueueItem(id, updates) {
    setUploadQueue(prev =>
      prev.map(item => (item.id === id ? { ...item, ...updates } : item)),
    );
  }

  function removeQueueItem(id) {
    setUploadQueue(prev => prev.filter(item => item.id !== id));
  }

  const getVideoDuration = (file) => {
    return new Promise((resolve) => {
      const video = document.createElement('video');
      video.preload = 'metadata';
      video.onloadedmetadata = () => {
        window.URL.revokeObjectURL(video.src);
        resolve(video.duration);
      };
      video.onerror = () => {
        window.URL.revokeObjectURL(video.src);
        resolve(0);
      };
      video.src = URL.createObjectURL(file);
    });
  };

  async function handleFiles(files) {
    for (const file of files) {
      const ext = file.name.split('.').pop().toLowerCase();
      if (!ALLOWED_EXTENSIONS.includes(ext)) {
        showNotification(`File type .${ext} is not supported. Please upload documents, images, or short videos.`, 'error');
        continue;
      }

      // Video duration check (max 10 mins)
      if (['mp4', 'webm', 'mov', 'avi', 'mkv'].includes(ext)) {
        const duration = await getVideoDuration(file);
        if (duration > VIDEO_MAX_DURATION) {
          showNotification(`Video "${file.name}" is too long (${Math.round(duration / 60)} mins). Max limit is 10 minutes.`, 'error');
          continue;
        }
      }

      const fileName = file.webkitRelativePath || file.name;
      const queueId = `${fileName}-${Date.now()}`;
      const queueItem = {
        id: queueId,
        name: fileName,
        size: file.size,
        progress: 0,
        status: UploadStatus.PENDING,
        uploadId: null,
      };

      setUploadQueue(prev => [...prev, queueItem]);

      if (isSmallFile(file)) {
        updateQueueItem(queueId, { status: UploadStatus.UPLOADING });
        try {
          await uploadFile(file);
          updateQueueItem(queueId, { status: UploadStatus.COMPLETE, progress: 1 });
          showNotification(`Processed ${file.name}`, 'success');
          onDocumentsChange?.();
          setTimeout(() => removeQueueItem(queueId), 3000);
        } catch (err) {
          updateQueueItem(queueId, { status: UploadStatus.FAILED });
          showNotification(`Error: ${err.message}`, 'error');
        }
      } else {
        try {
          const uploadId = await engine.uploadFile(file, {
            onProgress(progress) {
              updateQueueItem(queueId, { progress });
            },
            onStatusChange(status) {
              updateQueueItem(queueId, { status });
            },
            onComplete(result) {
              updateQueueItem(queueId, { status: UploadStatus.COMPLETE, progress: 1 });
              showNotification(result.message || `Processed ${file.name}`, 'success');
              onDocumentsChange?.();
              setTimeout(() => removeQueueItem(queueId), 3000);
            },
            onError(err) {
              updateQueueItem(queueId, { status: UploadStatus.FAILED });
              showNotification(`Error: ${err.message}`, 'error');
            },
          });
          updateQueueItem(queueId, { uploadId });
        } catch (err) {
          updateQueueItem(queueId, { status: UploadStatus.FAILED });
          showNotification(`Error: ${err.message}`, 'error');
        }
      }
    }
  }

  const availableProviders = useMemo(() => {
    return AI_TOOLS.filter(tool => localStorage.getItem(`api_key_${tool.id}`));
  }, [selectedToolId]); // Re-eval when tool changes as a proxy for key update

  const currentTool = AI_TOOLS.find(t => t.id === selectedToolId);
  const currentModel = currentTool?.models.find(m => m.id === selectedModelId);

  async function handleDeleteDocument(filename) {
    try {
      await deleteDocument(filename);
      showNotification('Document removed', 'success');
      onDocumentsChange(); // Refresh document list
    } catch (err) {
      showNotification(err.message || 'Failed to remove document', 'error');
    }
  }

  async function handleSend(overrideQuery = null, skipFailover = false) {
    const textToSend = typeof overrideQuery === 'string' ? overrideQuery : query;
    const finalQuery = selectedChip ? `${selectedChip.query}${textToSend}` : textToSend;
    const trimmed = finalQuery.trim();
    if (!trimmed || isGenerating) return;

    // ── Unsupported Feature Guard ──────────────────────────────────────────
    // Check before any API call so we never burn a round-trip.
    const guardResult = checkUnsupportedFeature(trimmed);
    if (guardResult.detected) {
      const userMsg   = { role: 'user',      content: trimmed };
      const assistMsg = { role: 'assistant', content: guardResult.message, intent: 'unsupported', sources: [] };
      setMessages((prev) => [...prev, userMsg, assistMsg]);
      setQuery('');
      setSelectedChip(null);
      setShowWelcome(false);
      if (textareaRef.current) textareaRef.current.style.height = 'auto';
      showNotification(
        `"${guardResult.feature.label}" isn't supported — see the response below.`,
        'info'
      );
      return;
    }
    // ───────────────────────────────────────────────────────────────────────

    let currentToolId = selectedToolId;
    let currentModelId = selectedModelId;
    const originalToolId = selectedToolId;

    setIsGenerating(true);
    setStatus('Refining query...');

    // Automatic Key Validation & Failover
    const checkAndSwitch = (notify = true) => {
      const toolDef = AI_TOOLS.find(t => t.id === currentToolId);
      if (toolDef && !toolDef.requiresKey) return true;

      const currentKey = localStorage.getItem(`api_key_${currentToolId}`);
      if (!currentKey) {
        const nextProvider = AI_TOOLS.find(t => t.id !== currentToolId && localStorage.getItem(`api_key_${t.id}`));
        if (nextProvider) {
          if (notify) showNotification(`Switching to ${nextProvider.name} (Key missing for ${currentToolId})`, 'info');
          currentToolId = nextProvider.id;
          currentModelId = getDefaultModel(nextProvider.id)?.id;
          setSelectedToolId(currentToolId);
          setSelectedModelId(currentModelId);
          return true;
        } else {
          if (notify) showNotification(`No API key found for ${currentToolId} and no other providers configured.`, 'error');
          return false;
        }
      }
      return true; // Key exists for currentToolId
    };

    // Initial check for API key
    if (!checkAndSwitch(false)) { // Don't notify on initial check if no key, let the specific error message handle it
      setIsGenerating(false);
      setStatus('');
      showNotification(`Please save your API key for ${currentToolId} in the sidebar first.`, 'error');
      return;
    }

    const newUserMsg = { role: 'user', content: trimmed };
    setMessages(prev => [...prev, newUserMsg]);
    setQuery('');
    setSelectedChip(null);
    setShowWelcome(false);
    if (textareaRef.current) textareaRef.current.style.height = 'auto';

    setIsGenerating(true);
    setStatus('Thinking...');

    let assistantMsg = { role: 'assistant', content: '', intent: '', sources: [] };
    setMessages((prev) => [...prev, assistantMsg]);

    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          query: trimmed,
          provider: currentToolId,
          model: currentModelId,
          api_key: localStorage.getItem(`api_key_${currentToolId}`)
        }),
      });

      if (!response.ok) {
        let errMsg = `Error ${response.status}`;
        let isAuthError = response.status === 401 || response.status === 403 || response.status === 400;
        
        try {
          const errData = await response.json();
          errMsg = errData.error || errMsg;
          // Groq often returns specific error strings
          if (errMsg.toLowerCase().includes('api key') || errMsg.toLowerCase().includes('authentication') || errMsg.toLowerCase().includes('invalid')) {
            isAuthError = true;
          }
        } catch { /* response wasn't JSON */ }

        if (isAuthError && !skipFailover) {
          const nextProvider = AI_TOOLS.find(p => p.id !== currentToolId && localStorage.getItem(`api_key_${p.id}`));
          if (nextProvider) {
            showNotification(`${currentToolId} key failed. Automatic switch to ${nextProvider.name}.`, 'warning');
            setSelectedToolId(nextProvider.id);
            const nextModel = getDefaultModel(nextProvider.id);
            if (nextModel) setSelectedModelId(nextModel.id);
            
            // Remove the failed assistant message and try again
            setMessages(prev => prev.slice(0, -1));
            setIsGenerating(false);
            setTimeout(() => handleSend(textToSend, true), 100);
            return;
          }
        }
        throw new Error(errMsg);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop();

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue;
          const jsonStr = line.substring(6).trim();
          if (!jsonStr) continue;

          try {
            const data = JSON.parse(jsonStr);

            if (data.error) {
              throw new Error(data.error);
            }

            if (data.token) {
              assistantMsg = { ...assistantMsg, content: assistantMsg.content + data.token };
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = assistantMsg;
                return updated;
              });
              setStatus('Generating...');
            }

            if (data.done) {
              assistantMsg = { ...assistantMsg, intent: data.intent, sources: data.sources || [] };
              setMessages((prev) => {
                const updated = [...prev];
                updated[updated.length - 1] = assistantMsg;
                return updated;
              });
            }
          } catch (parseErr) {
            if (parseErr.message && !parseErr.message.includes('JSON')) {
              throw parseErr; // Re-throw real errors (from data.error)
            }
            console.warn('[SSE] Skipping malformed chunk:', jsonStr);
          }
        }
      }
    } catch (err) {
      assistantMsg = { ...assistantMsg, content: assistantMsg.content + `\n\n❌ **Error:** ${err.message}` };
      showNotification(err.message, 'error');
      setMessages((prev) => {
        const updated = [...prev];
        updated[updated.length - 1] = assistantMsg;
        return updated;
      });
    }

    setIsGenerating(false);
    setStatus('');
  }

  function handleKeyDown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleDeleteMessage(index) {
    if (isGenerating) return;
    setMessages(prev => {
      const newMessages = [...prev];
      let deleteCount = 1;
      for (let i = index + 1; i < newMessages.length; i++) {
        if (newMessages[i].role === 'user') break;
        deleteCount++;
      }
      newMessages.splice(index, deleteCount);
      if (newMessages.length === 0) setShowWelcome(true);
      return newMessages;
    });
  }

  async function handleEditMessage(index, newContent) {
    if (isGenerating) return;

    // Remove the message being edited and everything after it
    setMessages(prev => prev.slice(0, index));

    // Resend the new content
    await handleSend(newContent);
  }

  function handleInput(e) {
    setQuery(e.target.value);
    e.target.style.height = 'auto';
    e.target.style.height = Math.min(e.target.scrollHeight, 120) + 'px';
  }

  function handleChip(chip) {
    setSelectedChip(chip);
    textareaRef.current?.focus();
  }

  function handleAddCustomChip() {
    if (!newChipLabel.trim() || !newChipQuery.trim()) return;
    const newChip = { label: newChipLabel.trim(), query: newChipQuery.trim() };
    const updated = [...customChips, newChip];
    setCustomChips(updated);
    localStorage.setItem('custom_chips', JSON.stringify(updated));
    setNewChipLabel('');
    setNewChipQuery('');
    setShowAddChip(false);
    showNotification(`New template "${newChipLabel}" added!`, 'success');
  }

  function deleteCustomChip(label) {
    const updated = customChips.filter(c => c.label !== label);
    setCustomChips(updated);
    localStorage.setItem('custom_chips', JSON.stringify(updated));
    if (selectedChip?.label === label) setSelectedChip(null);
    showNotification('Template deleted', 'info');
  }

  return (
    <main className="main-content">
      {/* Floating sidebar toggle */}
      <button
        className="sidebar-toggle-float"
        onClick={onToggleSidebar}
        aria-label="Toggle Sidebar"
        title={sidebarOpen ? "Hide Sidebar" : "Show Sidebar"}
        style={{ position: 'fixed', top: 16, left: 16 }}
      >
        <Menu size={18} />
      </button>

      {/* Floating theme toggle */}
      <button
        className="theme-toggle"
        onClick={(e) => toggleTheme(e)}
        aria-label="Toggle Theme"
        title={`Switch to ${theme === 'dark' ? 'Light' : 'Dark'} Mode`}
        style={{ position: 'fixed', top: 16, right: 16 }}
      >
        {theme === 'dark' ? <Sun size={18} /> : <Moon size={18} />}
      </button>

      {/* Navbar hidden but preserved */}
      <header className="topbar" style={{ display: 'none' }}>
        <div className="topbar-left">
          <button className="topbar-menu" onClick={onOpenSidebar} aria-label="Menu">
            <Menu size={20} />
          </button>
          <div className="topbar-brand">
            <img src="/AskiFy_Logo.png" alt="AskiFy" className="topbar-logo" />
          </div>
        </div>
        <div className="topbar-center">
        </div>
        <div className="topbar-status">
          <button
            className="topbar-action-btn"
            onClick={() => setShowSettings(true)}
            aria-label="Settings"
            title="Model & API Settings"
            style={{ display: 'none' }}
          >
            <Menu size={18} />
            <span className="btn-label">Api</span>
          </button>
        </div>
      </header>

      {/* Conversation */}
      <div className="conversation">
        <div className="conversation-inner">
          {showWelcome && (
            <div className="welcome">
              <div className="welcome-badge">
                <Sparkles size={12} style={{ marginRight: '6px' }} />
                AI Academic Assistant
              </div>
              <h2 className="welcome-heading">What can I help you study?</h2>
              <p className="welcome-sub">Upload your materials and ask anything — explanations, comparisons, solutions, study plans.</p>
              


              <div className="welcome-grid">
                {allChips.map((chip) => (
                  <div key={chip.label} className="welcome-card-wrapper" style={{ position: 'relative' }}>
                    <button className="welcome-card" onClick={() => handleChip(chip)}>
                      <span className="welcome-card-icon">{chip.icon}</span>
                      <span className="welcome-card-label">{chip.label}</span>
                    </button>
                    {chip.isCustom && (
                      <button 
                        className="chip-delete-float" 
                        onClick={(e) => { e.stopPropagation(); deleteCustomChip(chip.label); }}
                        title="Delete template"
                      >
                        <X size={10} />
                      </button>
                    )}
                  </div>
                ))}
                <button className="welcome-card add-chip-card" onClick={() => setShowAddChip(true)}>
                  <span className="welcome-card-icon"><Sparkles size={16} /></span>
                  <span className="welcome-card-label">+ New Box</span>
                </button>
              </div>
            </div>
          )}

          <div className="messages">
            {messages.map((msg, i) => (
              <Message
                key={i}
                role={msg.role}
                content={msg.content}
                intent={msg.intent}
                sources={msg.sources}
                onDelete={() => handleDeleteMessage(i)}
                onEdit={(newContent) => handleEditMessage(i, newContent)}
              />
            ))}
            {isGenerating && (!messages.length || messages[messages.length - 1].content === '') && <LoadingMessage />}
            <div ref={messagesEndRef} />
          </div>
        </div>
      </div>

      {/* Composer */}
      <div className="composer">
        <div className="composer-inner">
          {!showWelcome && !selectedChip && (
            <div className="composer-chips">
              {allChips.map((chip) => (
                <div key={chip.label} className="chip-wrapper" style={{ display: 'flex', alignItems: 'center' }}>
                  <button className="chip" onClick={() => handleChip(chip)}>
                    {chip.icon} {chip.label}
                  </button>
                  {chip.isCustom && (
                    <button 
                      className="chip-delete-btn" 
                      onClick={() => deleteCustomChip(chip.label)}
                      title="Delete"
                    >
                      <X size={10} />
                    </button>
                  )}
                </div>
              ))}
              <button className="chip add-chip-btn" onClick={() => setShowAddChip(true)}>
                + Add
              </button>
            </div>
          )}
          
          {status && (
            <div className="composer-status">
              <Sparkles size={12} className="status-icon" />
              <span>{status}</span>
            </div>
          )}

          {documents.length > 0 && (
            <div className="composer-knowledge-panel">
              <div className="composer-knowledge-chips">
                {documents.map(doc => (
                  <div key={doc.name} className="knowledge-chip" title={`${doc.name} (${doc.size_formatted})`}>
                    <FileText size={12} />
                    <span className="knowledge-chip-name">{doc.name}</span>
                    <button 
                      className="knowledge-chip-remove" 
                      onClick={() => handleDeleteDocument(doc.name)}
                      title="Remove document"
                    >
                      <X size={10} />
                    </button>
                  </div>
                ))}
              </div>
              <div className="composer-knowledge-summary">
                <FileText size={12} />
                <span>{documents.length} documents indexed ({totalChunks} units of knowledge)</span>
              </div>
            </div>
          )}
          
          {uploadQueue.length > 0 && (

            <div className="composer-upload-queue">
              {uploadQueue.map(item => (
                <div key={item.id} className={`composer-upload-item status-${item.status.toLowerCase()}`}>
                  <div className="upload-item-info">
                    <span className="upload-item-name">{item.name}</span>
                    <span className="upload-item-percent">{Math.round(item.progress * 100)}%</span>
                  </div>
                  <div className="upload-progress-bar">
                    <div className="upload-progress-fill" style={{ width: `${item.progress * 100}%` }} />
                  </div>
                </div>
              ))}
            </div>
          )}



          <div className="composer-box">
            <div className="composer-upload-container">
              <button 
                className={`composer-upload-btn ${showUploadMenu ? 'active' : ''}`} 
                onClick={() => setShowUploadMenu(!showUploadMenu)}
                title="Upload"
                type="button"
              >
                <Plus size={20} />
              </button>
              
              {showUploadMenu && (
                <>
                  <div className="upload-menu-overlay" onClick={() => setShowUploadMenu(false)} />
                  <div className="composer-upload-menu">
                    <button onClick={() => { fileInputRef.current?.click(); setShowUploadMenu(false); }}>
                      <FileText size={16} />
                      <span>Upload Files</span>
                    </button>
                    <button onClick={() => { folderInputRef.current?.click(); setShowUploadMenu(false); }}>
                      <Folder size={16} />
                      <span>Upload Folder</span>
                    </button>
                  </div>
                </>
              )}
            </div>
            
            <input 
              type="file" 
              ref={fileInputRef} 
              multiple 
              hidden 
              onChange={(e) => {
                if (e.target.files.length) handleFiles(e.target.files);
                e.target.value = '';
              }}
            />
            <input 
              type="file" 
              ref={folderInputRef} 
              webkitdirectory="" 
              mozdirectory="" 
              hidden 
              onChange={(e) => {
                if (e.target.files.length) handleFiles(e.target.files);
                e.target.value = '';
              }}
            />
            {selectedChip && (
              <div className="composer-selected-chip">
                <span className="chip-icon">{selectedChip.icon}</span>
                <span className="chip-label">{selectedChip.label}</span>
                <button 
                  className="chip-close" 
                  onClick={() => setSelectedChip(null)}
                  title="Remove template"
                >
                  <X size={12} />
                </button>
              </div>
            )}
            <textarea
              ref={textareaRef}
              placeholder={selectedChip ? "Add details..." : "Ask about your study materials…"}
              rows="1"
              value={query}
              onChange={handleInput}
              onKeyDown={handleKeyDown}
            />
            <button className="send-btn" onClick={() => handleSend()} disabled={isGenerating || (!query.trim() && !selectedChip)} title="Send">
              <Send size={18} />
            </button>
          </div>
        </div>
      </div>

      {/* Add Custom Chip Modal */}
      {showAddChip && (
        <div className="modal-overlay" onClick={() => setShowAddChip(false)}>
          <div className="modal-content" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Create Custom Template</h3>
              <button className="modal-close" onClick={() => setShowAddChip(false)}><X size={18} /></button>
            </div>
            <div className="modal-body">
              <div className="input-group">
                <label>Label</label>
                <input 
                  type="text" 
                  placeholder="e.g. Write Code" 
                  value={newChipLabel} 
                  onChange={e => setNewChipLabel(e.target.value)}
                />
              </div>
              <div className="input-group">
                <label>Prompt Template (Prefix)</label>
                <textarea 
                  placeholder="e.g. Write a clean React component for..."
                  value={newChipQuery} 
                  onChange={e => setNewChipQuery(e.target.value)}
                  style={{ height: '80px', paddingTop: '10px' }}
                />
              </div>
              <button 
                className="modal-submit" 
                onClick={handleAddCustomChip}
                disabled={!newChipLabel.trim() || !newChipQuery.trim()}
              >
                Create Selection Box
              </button>
            </div>
          </div>
        </div>
      )}
      {/* Settings Modal */}
      {showSettings && (
        <div className="modal-overlay" onClick={() => setShowSettings(false)}>
          <div className="modal-content settings-modal" onClick={e => e.stopPropagation()}>
            <div className="modal-header">
              <div className="header-title-row">
                <Settings size={20} />
                <h3>Model Settings</h3>
              </div>
              <button className="modal-close" onClick={() => setShowSettings(false)}><X size={18} /></button>
            </div>
            <div className="modal-body">
              <div className="settings-section" style={{ display: 'none' }}>
                <div className="settings-section-title">
                  <Sparkles size={14} />
                  <span>Provider & Model</span>
                </div>
                <div className="settings-config-group">
                  <ToolSelector
                    selectedToolId={selectedToolId}
                    onToolChange={(id) => {
                      setSelectedToolId(id);
                      setSelectedModelId(getDefaultModel(id)?.id);
                    }}
                  />
                  <ModelSelector
                    selectedToolId={selectedToolId}
                    selectedModelId={selectedModelId}
                    onModelChange={setSelectedModelId}
                  />
                </div>
              </div>

              <div className="settings-section" style={{ display: 'none' }}>
                <div className="settings-section-title">
                  <Key size={14} />
                  <span>Knowledge Unit Authentication</span>
                </div>
                <ApiKeyInput
                  toolId={selectedToolId}
                  toolName={currentTool?.name || 'Selected Provider'}
                  showNotification={showNotification}
                />
              </div>

              <button className="modal-submit" onClick={() => setShowSettings(false)}>
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
}
