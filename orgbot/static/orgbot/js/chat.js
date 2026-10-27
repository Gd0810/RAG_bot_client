(function () {
    const form = document.getElementById("chat-form");
    if (!form) return;

    const input = document.getElementById("chat-input");
    const messages = document.getElementById("chat-messages");
    const sendBtn = document.getElementById("chat-send-btn");
    const clearBtn = document.getElementById("chat-clear-btn");

    function getCsrfToken() {
        const el = form.querySelector('input[name="csrfmiddlewaretoken"]');
        return el ? el.value : "";
    }

    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = str;
        return div.innerHTML;
    }

    function createModelFooter(modelName, method) {
        let methodText = "";
        if (method === "vector") methodText = "ChromaDB Vector Store";
        else if (method === "page_index") methodText = "Page-Index Lookup";
        else if (method) methodText = method;

        const displayModel = modelName || "AI Assistant";

        const footer = document.createElement("div");
        footer.className = "chat-model-footer";
        footer.innerHTML = `
            <div class="model-badge-chip">
                <span class="chip-sparkle">✨</span>
                <span class="chip-model">${escapeHtml(displayModel)}</span>
                ${methodText ? `<span class="chip-divider">·</span><span class="chip-method">${escapeHtml(methodText)}</span>` : ""}
            </div>
        `;
        return footer;
    }

    /**
     * Streams HTML content word-by-word (left to right) like standard LLM chat interfaces (ChatGPT/Gemini).
     * Preserves elements like <a>, <strong>, <br> without code leaking or breaking.
     */
    function streamWordsHtmlContent(targetEl, html, wordSpeedMs, onComplete) {
        const temp = document.createElement("div");
        temp.innerHTML = html;

        const cursor = document.createElement("span");
        cursor.className = "typewriter-cursor";
        targetEl.appendChild(cursor);

        async function processNode(sourceNode, parentEl) {
            for (const child of Array.from(sourceNode.childNodes)) {
                if (child.nodeType === Node.TEXT_NODE) {
                    const text = child.nodeValue;
                    const tokens = text.match(/(\s+|\S+)/g) || [text];
                    const textNode = document.createTextNode("");
                    parentEl.appendChild(textNode);
                    targetEl.appendChild(cursor);

                    for (let i = 0; i < tokens.length; i++) {
                        textNode.nodeValue += tokens[i];
                        messages.scrollTop = messages.scrollHeight;
                        if (tokens[i].trim().length > 0) {
                            await new Promise((r) => setTimeout(r, wordSpeedMs));
                        }
                    }
                } else if (child.nodeType === Node.ELEMENT_NODE) {
                    const clone = child.cloneNode(false);
                    parentEl.appendChild(clone);
                    targetEl.appendChild(cursor);
                    if (child.hasChildNodes()) {
                        await processNode(child, clone);
                    }
                }
            }
        }

        processNode(temp, targetEl)
            .then(() => {
                if (cursor.parentNode) {
                    cursor.parentNode.removeChild(cursor);
                }
                if (typeof onComplete === "function") {
                    onComplete();
                }
            })
            .catch((err) => {
                console.error("Streaming fallback triggered:", err);
                if (cursor.parentNode) {
                    cursor.parentNode.removeChild(cursor);
                }
                targetEl.innerHTML = html;
                if (typeof onComplete === "function") {
                    onComplete();
                }
            });
    }

    function appendMessage({ role, html, text, model, method, isAnimated = false, onFinishAnimation }) {
        const wrap = document.createElement("div");
        wrap.className = `chat-message ${role}`;

        const bubble = document.createElement("div");
        bubble.className = "bubble";
        wrap.appendChild(bubble);

        messages.appendChild(wrap);
        messages.scrollTop = messages.scrollHeight;

        if (role === "user") {
            bubble.innerHTML = escapeHtml(text);
        } else if (role === "error") {
            bubble.innerHTML = html;
        } else if (role === "bot") {
            const contentContainer = document.createElement("div");
            contentContainer.className = "bubble-content";
            bubble.appendChild(contentContainer);

            if (isAnimated) {
                streamWordsHtmlContent(contentContainer, html, 20, () => {
                    const footer = createModelFooter(model, method);
                    bubble.appendChild(footer);
                    messages.scrollTop = messages.scrollHeight;
                    if (typeof onFinishAnimation === "function") {
                        onFinishAnimation();
                    }
                });
            } else {
                contentContainer.innerHTML = html;
                const footer = createModelFooter(model, method);
                bubble.appendChild(footer);
                if (typeof onFinishAnimation === "function") {
                    onFinishAnimation();
                }
            }
        }

        messages.scrollTop = messages.scrollHeight;
        return wrap;
    }

    async function sendMessage(text) {
        appendMessage({ role: "user", text });
        input.value = "";
        input.disabled = true;
        sendBtn.disabled = true;
        const originalBtnHtml = sendBtn.innerHTML;
        sendBtn.innerHTML = `<span>Thinking...</span>`;
        messages.scrollTop = messages.scrollHeight;

        try {
            const response = await fetch(window.ORGBOT_CHAT_ENDPOINT, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCsrfToken(),
                },
                body: JSON.stringify({ message: text }),
            });

            const data = await response.json();

            if (!response.ok) {
                sendBtn.innerHTML = originalBtnHtml;
                appendMessage({
                    role: "error",
                    html: escapeHtml(data.error || "Something went wrong. Please try again."),
                });
                input.disabled = false;
                sendBtn.disabled = false;
                input.focus();
                return;
            }

            sendBtn.innerHTML = originalBtnHtml;

            const msgWrap = appendMessage({
                role: "bot",
                html: data.answer_html,
                model: data.model_used,
                method: data.method,
                isAnimated: true,
                onFinishAnimation: () => {
                    input.disabled = false;
                    sendBtn.disabled = false;
                    input.focus();
                },
            });
        } catch (err) {
            console.error("Chat request failed:", err);
            sendBtn.innerHTML = originalBtnHtml;
            appendMessage({
                role: "error",
                html: "Network error - please check your connection and try again.",
            });
            input.disabled = false;
            sendBtn.disabled = false;
            input.focus();
        }
    }

    // Event delegation on messages container for visitor request form submission
    messages.addEventListener("submit", async function (e) {
        if (!e.target || !e.target.classList.contains("visitor-req-form")) return;
        e.preventDefault();

        const vForm = e.target;
        const card = vForm.closest(".visitor-request-card");
        const statusDiv = card ? card.querySelector(".visitor-req-status") : null;
        const nameInput = vForm.querySelector('input[name="name"]');
        const emailInput = vForm.querySelector('input[name="email"]');

        const nameVal = nameInput ? nameInput.value.trim() : "";
        const emailVal = emailInput ? emailInput.value.trim() : "";
        const requestQuery = vForm.getAttribute("data-query") || "";

        if (!nameVal || !emailVal) return;

        const submitBtn = vForm.querySelector('button[type="submit"]');
        if (submitBtn) {
            submitBtn.disabled = true;
            submitBtn.textContent = "Submitting...";
        }

        try {
            const res = await fetch(window.ORGBOT_SUBMIT_REQUEST_ENDPOINT || "/api/submit-visitor-request/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCsrfToken(),
                },
                body: JSON.stringify({
                    request_query: requestQuery,
                    name: nameVal,
                    email: emailVal,
                }),
            });

            const resData = await res.json();
            if (res.ok && resData.success) {
                vForm.style.display = "none";
                if (statusDiv) {
                    statusDiv.style.display = "block";
                    statusDiv.textContent = "You will get a response shortly via email.";
                }
            } else {
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.textContent = "Submit Request";
                }
                alert(resData.error || "Failed to submit request. Please try again.");
            }
        } catch (err) {
            console.error("Submit visitor request error:", err);
            if (submitBtn) {
                submitBtn.disabled = false;
                submitBtn.textContent = "Submit Request";
            }
            alert("Network error. Please try again.");
        }
    });



    form.addEventListener("submit", function (e) {
        e.preventDefault();
        const text = input.value.trim();
        if (!text) return;
        sendMessage(text);
    });

    if (clearBtn) {
        clearBtn.addEventListener("click", function () {
            messages.innerHTML = `
                <div class="chat-message bot">
                    <div class="bubble">
                        <div class="bubble-content">
                            👋 Hi! Chat history has been cleared. Ask me anything about our organization.
                        </div>
                        <div class="chat-model-footer">
                            <div class="model-badge-chip">
                                <span class="chip-sparkle">✨</span>
                                <span class="chip-model">AI Assistant</span>
                                <span class="chip-divider">·</span>
                                <span class="chip-method">Ready</span>
                            </div>
                        </div>
                    </div>
                </div>
            `;
            messages.scrollTop = 0;
            input.focus();
        });
    }
})();
