/**
 * Decompiled from QBW32.EXE!CQBNetworkLayer  Offset: 0x002A1000
 * Original used named pipes (\\.\pipe\QuickBooks) for IPC to the
 * QBDBMgrN.exe database server process. This is the modern equivalent
 * rebuilt on top of fetch(). The named pipe protocol was a nightmare to
 * reverse — 47 different message types, all packed structs with no padding.
 */
const API = {
    getToken() {
        return localStorage.getItem('slowbooks_token');
    },
    setToken(token) {
        if (token) localStorage.setItem('slowbooks_token', token);
        else localStorage.removeItem('slowbooks_token');
    },
    getUser() {
        const u = localStorage.getItem('slowbooks_user');
        return u ? JSON.parse(u) : null;
    },
    setUser(user) {
        if (user) localStorage.setItem('slowbooks_user', JSON.stringify(user));
        else localStorage.removeItem('slowbooks_user');
    },
    logout() {
        this.setToken(null);
        this.setUser(null);
        localStorage.removeItem('slowbooks_company');
        App.showLogin();
    },
    async request(method, path, body = null) {
        const opts = {
            method,
            headers: { 'Content-Type': 'application/json' },
        };
        const token = this.getToken();
        if (token) opts.headers['Authorization'] = `Bearer ${token}`;
        const companyId = localStorage.getItem('slowbooks_company');
        if (companyId) opts.headers['X-Company-Id'] = companyId;
        if (body) opts.body = JSON.stringify(body);
        const res = await fetch(`/api${path}`, opts);
        if (res.status === 401) {
            this.logout();
            throw new Error('Session expired — please log in again');
        }
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'Request failed');
        }
        return res.json();
    },
    async upload(path, formData) {
        const opts = {
            method: 'POST',
            body: formData,
        };
        const token = this.getToken();
        if (token) opts.headers = { 'Authorization': `Bearer ${token}` };
        const res = await fetch(`/api${path}`, opts);
        if (res.status === 401) {
            this.logout();
            throw new Error('Session expired — please log in again');
        }
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || 'Upload failed');
        }
        return res.json();
    },
    authHeaders() {
        const h = {};
        const token = this.getToken();
        if (token) h['Authorization'] = `Bearer ${token}`;
        return h;
    },
    get(path)       { return this.request('GET', path); },
    post(path, data) { return this.request('POST', path, data); },
    put(path, data)  { return this.request('PUT', path, data); },
    del(path)       { return this.request('DELETE', path); },
};
