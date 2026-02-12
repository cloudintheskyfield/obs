// Omni Agent 前端应用主脚本
class OmniAgentApp {
    constructor() {
        this.apiBaseUrl = 'http://127.0.0.1:8000';  // Docker mode
        this.fallbackUrl = 'http://127.0.0.1:8002'; // Local mode (new port)
        this.sessions = new Map(); // 存储所有会话
        this.currentSessionId = null;
        this.agentStatus = 'disconnected';
        this.skills = [];
        
        this.init();
    }

    async init() {
        this.initializeElements();
        this.bindEvents();
        this.loadSettings();
        await this.checkAgentStatus();
        this.loadSessions();
        this.applyTheme();
    }

    initializeElements() {
        // 基本元素
        this.chatMessages = document.getElementById('chat-messages');
        this.messageInput = document.getElementById('message-input');
        this.sendBtn = document.getElementById('send-btn');
        this.newChatBtn = document.getElementById('new-chat-btn');
        this.sessionList = document.getElementById('session-list');
        this.agentStatusEl = document.getElementById('agent-status');
        this.skillsInfoEl = document.getElementById('skills-info');
        this.skillsCountEl = document.getElementById('skills-count');
        this.skillsListEl = document.getElementById('skills-list');
        this.skillsSearchEl = document.getElementById('skills-search');
        this.currentSessionTitle = document.getElementById('current-session-title');
        this.welcomeScreen = document.getElementById('welcome-screen');
        this.loadingOverlay = document.getElementById('loading-overlay');
        
        // 控制按钮
        this.clearChatBtn = document.getElementById('clear-chat-btn');
        this.exportChatBtn = document.getElementById('export-chat-btn');
        this.settingsBtn = document.getElementById('settings-btn');
        
        // 模态框
        this.settingsModal = document.getElementById('settings-modal');
        this.closeSettingsBtn = document.getElementById('close-settings');
        this.saveSettingsBtn = document.getElementById('save-settings');
        this.resetSettingsBtn = document.getElementById('reset-settings');
        
        // 设置输入
        this.apiUrlInput = document.getElementById('api-url');
        this.autoSaveInput = document.getElementById('auto-save');
        this.themeSelect = document.getElementById('theme-select');
    }

    bindEvents() {
        // 发送消息
        this.sendBtn.addEventListener('click', () => this.sendMessage());
        this.messageInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        // 自动调整输入框高度
        this.messageInput.addEventListener('input', () => {
            this.messageInput.style.height = 'auto';
            this.messageInput.style.height = this.messageInput.scrollHeight + 'px';
        });

        // 新建会话
        this.newChatBtn.addEventListener('click', () => this.createNewSession());

        // 快捷命令
        document.querySelectorAll('.quick-cmd').forEach(btn => {
            btn.addEventListener('click', () => {
                const cmd = btn.dataset.cmd;
                this.messageInput.value = cmd;
                this.messageInput.focus();
            });
        });

        // 快捷操作卡片
        document.querySelectorAll('.action-card').forEach(card => {
            card.addEventListener('click', () => {
                const command = card.dataset.command;
                this.messageInput.value = command;
                this.sendMessage();
            });
        });

        // 控制按钮
        this.clearChatBtn.addEventListener('click', () => this.clearCurrentChat());
        this.exportChatBtn.addEventListener('click', () => this.exportCurrentChat());
        this.settingsBtn.addEventListener('click', () => this.openSettings());

        // 设置模态框
        this.closeSettingsBtn.addEventListener('click', () => this.closeSettings());
        this.saveSettingsBtn.addEventListener('click', () => this.saveSettings());
        this.resetSettingsBtn.addEventListener('click', () => this.resetSettings());
        
        // 点击模态框外部关闭
        this.settingsModal.addEventListener('click', (e) => {
            if (e.target === this.settingsModal) {
                this.closeSettings();
            }
        });

        // 主题切换
        this.themeSelect.addEventListener('change', () => this.applyTheme());

        if (this.skillsSearchEl) {
            this.skillsSearchEl.addEventListener('input', () => this.renderSkillsList());
        }

        // 定期检查Agent状态
        setInterval(() => this.checkAgentStatus(), 30000);
    }

    // 会话管理
    createNewSession() {
        const sessionId = 'session_' + Date.now();
        const session = {
            id: sessionId,
            title: '新对话',
            messages: [],
            createdAt: new Date(),
            updatedAt: new Date()
        };
        
        this.sessions.set(sessionId, session);
        this.switchToSession(sessionId);
        this.updateSessionList();
        this.saveSessionsToStorage();
    }

    switchToSession(sessionId) {
        // 保存当前会话
        if (this.currentSessionId && this.sessions.has(this.currentSessionId)) {
            this.saveCurrentSession();
        }

        this.currentSessionId = sessionId;
        const session = this.sessions.get(sessionId);
        
        if (session) {
            this.loadSessionMessages(session);
            this.currentSessionTitle.textContent = session.title;
            this.welcomeScreen.style.display = 'none';
            this.chatMessages.style.display = 'block';
        }

        this.updateSessionList();
    }

    saveCurrentSession() {
        if (!this.currentSessionId) return;
        
        const session = this.sessions.get(this.currentSessionId);
        if (session) {
            session.updatedAt = new Date();
            this.saveSessionsToStorage();
        }
    }

    loadSessionMessages(session) {
        this.chatMessages.innerHTML = '';
        session.messages.forEach(message => {
            this.displayMessage(message, false);
        });
        this.scrollToBottom();
    }

    updateSessionList() {
        this.sessionList.innerHTML = '';
        
        const sortedSessions = Array.from(this.sessions.values())
            .sort((a, b) => new Date(b.updatedAt) - new Date(a.updatedAt));

        sortedSessions.forEach(session => {
            const sessionEl = document.createElement('div');
            sessionEl.className = 'session-item';
            sessionEl.dataset.sessionId = session.id;
            
            if (session.id === this.currentSessionId) {
                sessionEl.classList.add('active');
            }

            const lastMessage = session.messages[session.messages.length - 1];
            const preview = lastMessage ? 
                (lastMessage.content.length > 30 ? 
                    lastMessage.content.substring(0, 30) + '...' : 
                    lastMessage.content) : '开始新对话...';

            sessionEl.innerHTML = `
                <div class="session-title">${session.title}</div>
                <div class="session-time">${this.formatTime(session.updatedAt)}</div>
                <div class="session-preview">${preview}</div>
            `;

            sessionEl.addEventListener('click', () => {
                this.switchToSession(session.id);
            });

            // 双击编辑标题
            sessionEl.addEventListener('dblclick', () => {
                this.editSessionTitle(session.id);
            });

            this.sessionList.appendChild(sessionEl);
        });
    }

    editSessionTitle(sessionId) {
        const session = this.sessions.get(sessionId);
        if (!session) return;

        const newTitle = prompt('修改会话标题:', session.title);
        if (newTitle && newTitle.trim()) {
            session.title = newTitle.trim();
            this.updateSessionList();
            if (sessionId === this.currentSessionId) {
                this.currentSessionTitle.textContent = session.title;
            }
            this.saveSessionsToStorage();
        }
    }

    clearCurrentChat() {
        if (!this.currentSessionId) return;
        
        if (confirm('确定要清空当前对话吗？此操作不可撤销。')) {
            const session = this.sessions.get(this.currentSessionId);
            if (session) {
                session.messages = [];
                this.chatMessages.innerHTML = '';
                this.saveSessionsToStorage();
            }
        }
    }

    exportCurrentChat() {
        if (!this.currentSessionId) {
            this.showNotification('没有可导出的对话', 'warning');
            return;
        }

        const session = this.sessions.get(this.currentSessionId);
        if (!session || session.messages.length === 0) {
            this.showNotification('当前对话为空', 'warning');
            return;
        }

        const exportData = {
            title: session.title,
            exportTime: new Date().toISOString(),
            messages: session.messages
        };

        const blob = new Blob([JSON.stringify(exportData, null, 2)], {
            type: 'application/json'
        });

        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `omni-agent-chat-${session.title}-${Date.now()}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        this.showNotification('对话已导出', 'success');
    }

    // 消息处理
    async sendMessage() {
        const content = this.messageInput.value.trim();
        if (!content) return;

        // 如果没有当前会话，创建一个新的
        if (!this.currentSessionId) {
            this.createNewSession();
        }

        // 清空输入框
        this.messageInput.value = '';
        this.messageInput.style.height = 'auto';
        this.sendBtn.disabled = true;

        // 显示用户消息
        const userMessage = {
            role: 'user',
            content: content,
            timestamp: new Date()
        };
        
        this.addMessageToSession(userMessage);
        this.displayMessage(userMessage);
        this.hideWelcomeScreen();

        // 发送到Agent
        this.showLoading();
        
        try {
            const response = await this.callAgent(content);
            
            const assistantMessage = {
                role: 'assistant',
                content: response.content || response.error || '处理出错',
                timestamp: new Date(),
                success: response.success,
                metadata: response.metadata
            };
            
            this.addMessageToSession(assistantMessage);
            this.displayMessage(assistantMessage);
            
            // 更新会话标题（使用第一条用户消息）
            this.updateSessionTitle();
            
        } catch (error) {
            console.error('Send message error:', error);
            const errorMessage = {
                role: 'assistant',
                content: `连接失败: ${error.message}`,
                timestamp: new Date(),
                success: false,
                error: true
            };
            
            this.addMessageToSession(errorMessage);
            this.displayMessage(errorMessage);
        } finally {
            this.hideLoading();
            this.sendBtn.disabled = false;
            this.messageInput.focus();
        }
    }

    addMessageToSession(message) {
        if (this.currentSessionId) {
            const session = this.sessions.get(this.currentSessionId);
            if (session) {
                session.messages.push(message);
                session.updatedAt = new Date();
                this.saveSessionsToStorage();
            }
        }
    }

    updateSessionTitle() {
        if (!this.currentSessionId) return;
        
        const session = this.sessions.get(this.currentSessionId);
        if (session && session.title === '新对话' && session.messages.length > 0) {
            const firstUserMessage = session.messages.find(m => m.role === 'user');
            if (firstUserMessage) {
                const title = firstUserMessage.content.length > 20 ? 
                    firstUserMessage.content.substring(0, 20) + '...' : 
                    firstUserMessage.content;
                session.title = title;
                this.currentSessionTitle.textContent = title;
                this.updateSessionList();
                this.saveSessionsToStorage();
            }
        }
    }

    displayMessage(message, animate = true) {
        const messageEl = document.createElement('div');
        messageEl.className = `message ${message.role}`;
        if (message.error) messageEl.classList.add('error');
        if (message.success === false) messageEl.classList.add('error');
        if (message.success === true) messageEl.classList.add('success');

        const avatar = message.role === 'user' ? 
            '<i class="fas fa-user"></i>' : 
            '<i class="fas fa-robot"></i>';

        let content = this.formatMessageContent(message.content);

        messageEl.innerHTML = `
            <div class="message-avatar">${avatar}</div>
            <div class="message-content">
                <div class="message-text">${content}</div>
                <div class="message-time">${this.formatTime(message.timestamp)}</div>
            </div>
        `;

        this.chatMessages.appendChild(messageEl);
        this.scrollToBottom(animate);
    }

    formatMessageContent(content) {
        // 处理代码块
        content = content.replace(/```(\w+)?\n?([\s\S]*?)```/g, (match, lang, code) => {
            return `<div class="code-block"><pre><code>${this.escapeHtml(code.trim())}</code></pre></div>`;
        });

        // 处理行内代码
        content = content.replace(/`([^`]+)`/g, '<code>$1</code>');

        // 处理换行
        content = content.replace(/\n/g, '<br>');

        return content;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    hideWelcomeScreen() {
        this.welcomeScreen.style.display = 'none';
        this.chatMessages.style.display = 'block';
    }

    scrollToBottom(animate = true) {
        if (animate) {
            this.chatMessages.scrollTo({
                top: this.chatMessages.scrollHeight,
                behavior: 'smooth'
            });
        } else {
            this.chatMessages.scrollTop = this.chatMessages.scrollHeight;
        }
    }

    // Agent API 调用
    async callAgent(message) {
        // 解析命令格式
        const command = this.parseCommand(message);
        
        const response = await fetch(`${this.apiBaseUrl}/execute`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(command),
            timeout: 30000
        });

        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }

        return await response.json();
    }

    parseCommand(message) {
        // 文件操作命令
        if (message.startsWith('file:')) {
            const parts = message.substring(5).split(' ');
            const operation = parts[0];
            const path = parts[1];
            const content = parts.slice(2).join(' ');

            if (operation === 'create') {
                return {
                    tool_name: 'str_replace_editor',
                    parameters: {
                        command: 'create',
                        path: path,
                        file_text: content
                    }
                };
            } else if (operation === 'read') {
                return {
                    tool_name: 'str_replace_editor',
                    parameters: {
                        command: 'view',
                        path: path
                    }
                };
            }
        }

        // 命令执行
        if (message.startsWith('cmd:')) {
            return {
                tool_name: 'bash',
                parameters: {
                    command: message.substring(4).trim()
                }
            };
        }

        // 截图
        if (message.toLowerCase() === 'screenshot' || message.includes('截图') || message.includes('屏幕')) {
            return {
                tool_name: 'computer',
                parameters: {
                    action: 'screenshot'
                }
            };
        }

        // 默认作为bash命令处理
        if (message.includes('创建') && message.includes('文件')) {
            // 智能解析文件创建请求
            return this.parseFileCreationRequest(message);
        }

        if (message.includes('查看') && message.includes('目录')) {
            return {
                tool_name: 'bash',
                parameters: {
                    command: 'ls -la'
                }
            };
        }

        // 通用命令
        return {
            tool_name: 'bash',
            parameters: {
                command: message
            }
        };
    }

    parseFileCreationRequest(message) {
        // 简单的文件创建请求解析
        let filename = 'example.py';
        let content = "print('Hello World')";

        if (message.includes('Python') || message.includes('python') || message.includes('.py')) {
            filename = 'script.py';
            content = "#!/usr/bin/env python3\n\nprint('Hello from Omni Agent!')";
        } else if (message.includes('JavaScript') || message.includes('js') || message.includes('.js')) {
            filename = 'script.js';
            content = "console.log('Hello from Omni Agent!');";
        }

        return {
            tool_name: 'str_replace_editor',
            parameters: {
                command: 'create',
                path: filename,
                file_text: content
            }
        };
    }

    // Agent 状态检查
    async checkAgentStatus() {
        // Try Docker mode first
        try {
            const response = await fetch(`${this.apiBaseUrl}/health`, {
                timeout: 3000
            });
            
            if (response.ok) {
                this.agentStatus = 'connected';
                this.updateAgentStatusUI('Docker模式');
                await this.loadSkills();
                return;
            }
        } catch (error) {
            console.warn('Docker mode failed, trying local mode:', error);
        }
        
        // Fallback to local mode
        try {
            const response = await fetch(`${this.fallbackUrl}/health`, {
                timeout: 3000
            });
            
            if (response.ok) {
                this.agentStatus = 'connected';
                this.apiBaseUrl = this.fallbackUrl; // Switch to local mode
                this.updateAgentStatusUI('本地模式');
                await this.loadSkills();
                return;
            }
        } catch (error) {
            console.warn('Local mode also failed:', error);
        }
        
        // Both failed
        this.agentStatus = 'disconnected';
        this.updateAgentStatusUI('连接失败');
    }

    async loadSkills() {
        try {
            const response = await fetch(`${this.apiBaseUrl}/skills`);
            if (response.ok) {
                const data = await response.json();
                this.skills = data.skills || [];
                this.updateSkillsUI();
                this.renderSkillsList();
            }
        } catch (error) {
            console.warn('Failed to load skills:', error);
        }
    }

    updateAgentStatusUI(mode = '') {
        const statusDot = this.agentStatusEl.querySelector('.status-dot');
        const statusText = this.agentStatusEl.querySelector('span');

        if (this.agentStatus === 'connected') {
            statusDot.classList.add('online');
            statusText.textContent = mode ? `已连接 - ${mode}` : '已连接';
        } else {
            statusDot.classList.remove('online');
            statusText.textContent = mode || '连接失败';
        }
    }

    updateSkillsUI() {
        const text = this.skills.length > 0 ? 
            `技能: ${this.skills.length} 个可用` : 
            '技能: 加载失败';
        this.skillsInfoEl.textContent = text;

        if (this.skillsCountEl) {
            this.skillsCountEl.textContent = String(this.skills.length || 0);
        }
    }

    renderSkillsList() {
        if (!this.skillsListEl) return;

        const q = (this.skillsSearchEl?.value || '').trim().toLowerCase();
        const skills = (this.skills || []).filter(s => {
            const name = (s.name || '').toLowerCase();
            const desc = (s.description || '').toLowerCase();
            if (!q) return true;
            return name.includes(q) || desc.includes(q);
        });

        this.skillsListEl.innerHTML = '';
        skills.forEach(skill => {
            const el = document.createElement('div');
            el.className = 'skill-item';

            const toolName = skill.name || '';
            const description = skill.description || '';
            const chip = toolName === 'computer' ? 'GUI' : toolName === 'bash' ? 'Shell' : toolName === 'str_replace_editor' ? 'Files' : 'Tool';

            el.innerHTML = `
                <div class="skill-item-title">
                    <span>${this.escapeHtml(toolName)}</span>
                    <span class="skill-chip">${chip}</span>
                </div>
                <div class="skill-item-desc">${this.escapeHtml(description)}</div>
            `;

            el.addEventListener('click', () => {
                const example = this.getSkillExamplePrompt(toolName);
                this.messageInput.value = example;
                this.messageInput.focus();
                this.messageInput.dispatchEvent(new Event('input'));
            });

            this.skillsListEl.appendChild(el);
        });
    }

    getSkillExamplePrompt(toolName) {
        if (toolName === 'computer') return 'screenshot';
        if (toolName === 'bash') return 'cmd:ls -la';
        if (toolName === 'str_replace_editor') return 'file:read README.md';
        return toolName;
    }

    // 设置管理
    loadSettings() {
        const settings = localStorage.getItem('omni-agent-settings');
        if (settings) {
            try {
                const data = JSON.parse(settings);
                this.apiBaseUrl = data.apiUrl || this.apiBaseUrl;
                this.apiUrlInput.value = this.apiBaseUrl;
                this.autoSaveInput.checked = data.autoSave !== false;
                this.themeSelect.value = data.theme || 'light';
            } catch (error) {
                console.warn('Failed to load settings:', error);
            }
        }
    }

    saveSettings() {
        const settings = {
            apiUrl: this.apiUrlInput.value.trim(),
            autoSave: this.autoSaveInput.checked,
            theme: this.themeSelect.value
        };

        this.apiBaseUrl = settings.apiUrl;
        localStorage.setItem('omni-agent-settings', JSON.stringify(settings));
        
        this.applyTheme();
        this.closeSettings();
        this.checkAgentStatus(); // 重新检查连接
        
        this.showNotification('设置已保存', 'success');
    }

    resetSettings() {
        if (confirm('确定要重置所有设置吗？')) {
            localStorage.removeItem('omni-agent-settings');
            this.apiBaseUrl = 'http://127.0.0.1:8000';
            this.apiUrlInput.value = this.apiBaseUrl;
            this.autoSaveInput.checked = true;
            this.themeSelect.value = 'light';
            this.applyTheme();
            this.showNotification('设置已重置', 'success');
        }
    }

    openSettings() {
        this.settingsModal.classList.add('show');
    }

    closeSettings() {
        this.settingsModal.classList.remove('show');
    }

    applyTheme() {
        const theme = this.themeSelect.value;
        document.body.className = theme === 'auto' ? 'auto-theme' : 
                                  theme === 'dark' ? 'dark-theme' : '';
    }

    // 数据持久化
    saveSessionsToStorage() {
        if (this.autoSaveInput?.checked !== false) {
            const sessionsData = Array.from(this.sessions.entries()).map(([id, session]) => ({
                id,
                ...session
            }));
            localStorage.setItem('omni-agent-sessions', JSON.stringify(sessionsData));
        }
    }

    loadSessions() {
        try {
            const sessionsData = localStorage.getItem('omni-agent-sessions');
            if (sessionsData) {
                const sessions = JSON.parse(sessionsData);
                sessions.forEach(session => {
                    // 恢复日期对象
                    session.createdAt = new Date(session.createdAt);
                    session.updatedAt = new Date(session.updatedAt);
                    session.messages.forEach(msg => {
                        msg.timestamp = new Date(msg.timestamp);
                    });
                    this.sessions.set(session.id, session);
                });
                this.updateSessionList();
            }
        } catch (error) {
            console.warn('Failed to load sessions:', error);
        }

        // 如果没有会话，创建一个默认会话
        if (this.sessions.size === 0) {
            this.createNewSession();
        }
    }

    // 工具函数
    formatTime(date) {
        if (!(date instanceof Date)) {
            date = new Date(date);
        }
        
        const now = new Date();
        const diff = now - date;
        
        if (diff < 60000) { // 1分钟内
            return '刚刚';
        } else if (diff < 3600000) { // 1小时内
            return `${Math.floor(diff / 60000)}分钟前`;
        } else if (diff < 86400000) { // 1天内
            return `${Math.floor(diff / 3600000)}小时前`;
        } else {
            return date.toLocaleDateString();
        }
    }

    showNotification(message, type = 'info') {
        // 简单的通知显示
        const notification = document.createElement('div');
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 12px 20px;
            background: ${type === 'success' ? '#27ae60' : 
                        type === 'error' ? '#e74c3c' : 
                        type === 'warning' ? '#f39c12' : '#3498db'};
            color: white;
            border-radius: 6px;
            z-index: 10000;
            animation: slideIn 0.3s ease-out;
        `;
        notification.textContent = message;
        
        document.body.appendChild(notification);
        
        setTimeout(() => {
            notification.style.animation = 'slideOut 0.3s ease-out forwards';
            setTimeout(() => {
                document.body.removeChild(notification);
            }, 300);
        }, 3000);
    }

    showLoading() {
        this.loadingOverlay.classList.add('show');
    }

    hideLoading() {
        this.loadingOverlay.classList.remove('show');
    }
}

// 添加必要的CSS动画
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }
    
    @keyframes slideOut {
        from { transform: translateX(0); opacity: 1; }
        to { transform: translateX(100%); opacity: 0; }
    }
`;
document.head.appendChild(style);

// 初始化应用
document.addEventListener('DOMContentLoaded', () => {
    window.omniAgent = new OmniAgentApp();
});

// 全局错误处理
window.addEventListener('unhandledrejection', (event) => {
    console.error('Unhandled promise rejection:', event.reason);
    if (window.omniAgent) {
        window.omniAgent.showNotification('发生未知错误', 'error');
    }
});