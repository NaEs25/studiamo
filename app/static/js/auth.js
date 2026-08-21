// --- Studiamo Auth Module ---

async function loadUserProfiles() {
    // User switcher dropdown removed, profiles are selected via search on /login.
    // This function is a no-op kept for compatibility.
}

async function wizardSwitchProfile(username) {
    if (!username) return;
    await switchUserProfile(username);
}

async function continueAsTestUser() {
    activeUsername = 'test_user';
    localStorage.setItem('active_username', 'test_user');
    document.cookie = 'username=test_user; path=/; max-age=31536000';
    document.getElementById('overlay-wizard').classList.add('hidden');
    const fd = new FormData();
    fd.append('username', 'test_user');
    try { await fetchAPI('/api/users', { method: 'POST', body: fd }); } catch(e) {}
    loadUserProfiles();
    if (typeof loadDashboard === 'function') loadDashboard();
}

async function switchUserProfile(username) {
    try {
        const formData = new FormData();
        formData.append('username', username);
        let pwd = sessionStorage.getItem(`profile_password_${username}`) || '';
        if (pwd) {
            formData.append('password', pwd);
        }
        
        let res;
        try {
            res = await fetchAPI('/api/users/verify', {
                method: 'POST',
                body: formData
            });
        } catch (err) {
            // /api/users/verify returns three different 401s and only two of them are
            // worth prompting for: "Password required" and "Incorrect password". The
            // third says the account has no password and should sign in with Google,
            // and it has to fall through to the rethrow below, since prompting an
            // SSO user for a password they do not have is a dead end. That is why this
            // reads the message rather than err.status, which cannot tell them apart.
            // (fetchAPI deliberately exempts this URL from its redirect-on-401.)
            if (err.message && (err.message.includes("Password required") || err.message.includes("Incorrect password"))) {
                const promptFn = window.showPrompt || (typeof showPrompt === 'function' ? showPrompt : null);
                let inputPwd = null;
                if (promptFn) {
                    inputPwd = await promptFn({
                        title: "Profile Password Required",
                        message: `Enter password for profile "${username}":`,
                        inputType: "password"
                    });
                } else {
                    inputPwd = prompt(`Enter password for profile "${username}":`);
                }
                if (inputPwd === null) {
                    loadUserProfiles();
                    return;
                }
                const verifyData = new FormData();
                verifyData.append('username', username);
                verifyData.append('password', inputPwd);
                
                res = await fetchAPI('/api/users/verify', {
                    method: 'POST',
                    body: verifyData
                });
                pwd = inputPwd;
            } else {
                throw err;
            }
        }
        
        activeUsername = username;
        localStorage.setItem('active_username', username);
        localStorage.removeItem('active_studiamo_tab');
        if (pwd) {
            // Remembered per-username so switching back to a known profile within the
            // same tab session doesn't require retyping it. Not the same thing as the
            // removed profile_password cookie: this never leaves sessionStorage or gets
            // sent as a request header, the server authenticates via yb_session alone.
            sessionStorage.setItem(`profile_password_${username}`, pwd);
        }
        document.cookie = `username=${username}; path=/; max-age=31536000`;

        checkConfig();
        if (typeof loadDashboard === 'function') loadDashboard();
        if (typeof loadGoals === 'function') loadGoals();
        if (typeof loadStats === 'function') loadStats();
        if (typeof loadSettings === 'function') loadSettings();
    } catch (e) {
        console.error("Profile switch failed:", e);
        if (typeof showToast === 'function') {
            showToast("Failed to switch profile: " + e.message, "failed");
        } else {
            alert("Failed to switch profile: " + e.message);
        }
        loadUserProfiles();
    }
}

function openCreateUserModal() {
    const el = document.getElementById('overlay-create-user');
    if (el) el.classList.remove('hidden');
}

function closeCreateUserModal() {
    const el = document.getElementById('overlay-create-user');
    if (el) el.classList.add('hidden');
    const input = document.getElementById('create-username');
    if (input) input.value = '';
    const keyInput = document.getElementById('create-gemini-key');
    if (keyInput) keyInput.value = '';
    const pwdInput = document.getElementById('create-user-password');
    if (pwdInput) pwdInput.value = '';
}

async function handleCreateUserSubmit(event) {
    event.preventDefault();
    const input = document.getElementById('create-username');
    const newUsername = input.value.trim();
    if (!newUsername) return;
    
    const keyInput = document.getElementById('create-gemini-key');
    const geminiKey = keyInput ? keyInput.value.trim() : '';
    if (!geminiKey) {
        if (typeof showToast === 'function') {
            showToast("Google AI Studio API Key is required to create a profile.", "failed");
        } else {
            alert("Google AI Studio API Key is required to create a profile.");
        }
        return;
    }
    
    const pwdInput = document.getElementById('create-user-password');
    const pwd = pwdInput ? pwdInput.value.trim() : '';
    if (!pwd) {
        if (typeof showToast === 'function') {
            showToast("A password is required to create a profile.", "failed");
        } else {
            alert('A password is required to create a profile.');
        }
        return;
    }
    
    const formData = new FormData();
    formData.append('username', newUsername);
    formData.append('gemini_api_key', geminiKey);
    if (pwd) {
        formData.append('password', pwd);
    }
    
    showLoader("Creating Profile", "Initializing data environment for user " + newUsername + "...");
    try {
        await fetchAPI('/api/users', {
            method: 'POST',
            body: formData
        });
        closeCreateUserModal();
        hideLoader();
        
        if (pwd) {
            sessionStorage.setItem(`profile_password_${newUsername}`, pwd);
        }
        await switchUserProfile(newUsername);
    } catch (e) {
        hideLoader();
        console.error(e);
        if (typeof showToast === 'function') {
            showToast("Failed to create profile: " + e.message, "failed");
        } else {
            alert("Failed to create profile: " + e.message);
        }
    }
}

async function logoutUser() {
    try {
        await fetchAPI('/api/users/logout', { method: 'POST' });
    } catch(e) {}
    localStorage.removeItem('active_username');
    localStorage.removeItem('active_studiamo_tab');
    document.cookie = 'username=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
    document.cookie = 'profile_password=; path=/; expires=Thu, 01 Jan 1970 00:00:00 GMT';
    window.location.href = '/login';
}

async function checkConfig() {
    try {
        const data = await fetchAPI('/api/status');
        const wizard = document.getElementById('overlay-wizard');
        if (!data.is_configured && activeUsername !== 'test_user') {
            if (wizard) wizard.classList.remove('hidden');
        } else {
            if (wizard) wizard.classList.add('hidden');
            if (typeof loadDashboard === 'function') loadDashboard();
        }
    } catch (e) {
        console.error("Boot configuration check failed:", e);
    }
}

async function promptReportBug() {
    const confirmFn = window.showConfirm || (typeof showConfirm === 'function' ? showConfirm : null);
    let confirmed = false;
    if (confirmFn) {
        confirmed = await confirmFn({
            title: "Report a Bug?",
            message: "You will be redirected to the bug reporting page.",
            confirmText: "Go to Bug Tracker",
            icon: "alert-circle"
        });
    } else {
        confirmed = confirm("Möchtest du einen Bug melden?\n\nDu wirst zur Bug-Meldeseite weitergeleitet.");
    }
    if (confirmed) {
        window.location.href = "/dev/bugs";
    }
}

// Window bindings for inline HTML handlers
window.loadUserProfiles = loadUserProfiles;
window.wizardSwitchProfile = wizardSwitchProfile;
window.continueAsTestUser = continueAsTestUser;
window.switchUserProfile = switchUserProfile;
window.openCreateUserModal = openCreateUserModal;
window.closeCreateUserModal = closeCreateUserModal;
window.handleCreateUserSubmit = handleCreateUserSubmit;
window.logoutUser = logoutUser;
window.promptReportBug = promptReportBug;
window.checkConfig = checkConfig;

