import React, { useState, useEffect, useRef } from "react";
import { createRoot } from "react-dom/client";

const API_ENDPOINT = window.API_ENDPOINT || "YOUR_API_ENDPOINT_HERE";

const generateId = () => Math.random().toString(36).substring(2, 15);

const App = () => {
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState(null);
  const [userId] = useState(() => {
    const existing = localStorage.getItem("userId");
    if (existing) return existing;
    const id = generateId();
    localStorage.setItem("userId", id);
    return id;
  });
  const [sessionId, setSessionId] = useState(() => {
    const existing = localStorage.getItem("sessionId");
    if (existing) return existing;
    const id = generateId();
    localStorage.setItem("sessionId", id);
    return id;
  });

  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const fetchMessages = async () => {
    try {
      const response = await fetch(
        `${API_ENDPOINT}/messages?user_id=${userId}&session_id=${sessionId}&limit=50`
      );

      if (!response.ok) {
        throw new Error("Failed to fetch messages");
      }

      const data = await response.json();
      const messages = data?.body?.messages ?? [];
      setMessages(messages);
      setError(null);
      return messages;
    } catch (err) {
      console.error("Error fetching messages:", err);
      setError("Failed to load messages. Please check your API endpoint.");
      return [];
    }
  };

  useEffect(() => {
    fetchMessages();
  }, [sessionId]);

  const pollForAssistantResponse = async (userMessageTimestamp) => {
    let retries = 0;
    const maxRetries = 15; // ~30 seconds
    const pollInterval = 2000;

    while (retries < maxRetries) {
      retries++;

      try {
        const newMessages = await fetchMessages();

        const hasNewAssistantResponse = newMessages.some(
          (m) => m.role === "assistant" && m.created_at > userMessageTimestamp
        );

        if (hasNewAssistantResponse) break;

        await new Promise((resolve) => setTimeout(resolve, pollInterval));
      } catch (err) {
        console.error("Polling error:", err);
        break;
      }
    }

    setIsLoading(false);
  };

  const sendMessage = async (e) => {
    e.preventDefault();

    if (!inputValue.trim() || isLoading) return;

    const messageContent = inputValue.trim();
    setInputValue("");
    setIsLoading(true);
    setError(null);

    try {
      const response = await fetch(`${API_ENDPOINT}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          user_id: userId,
          session_id: sessionId,
          content: messageContent,
        }),
      });

      if (!response.ok) {
        throw new Error("Failed to send message");
      }

      const responseData = await response.json();
      const userMessageTimestamp = responseData.body.timestamp;

      await fetchMessages();

      await pollForAssistantResponse(userMessageTimestamp);
    } catch (err) {
      console.error("Error sending message:", err);
      setError("Failed to send message. Please try again.");
      setIsLoading(false);
    }
  };

  const startNewSession = () => {
    const newSessionId = generateId();
    setSessionId(newSessionId);
    localStorage.setItem("sessionId", newSessionId);
    setMessages([]);
    setError(null);
  };

  const formatContent = (content) => {
    if (typeof content === "string") return content;
    return JSON.stringify(content, null, 2);
  };

  return (
    <div className="app">
      <div className="header">
        <h1>🤖 LLM Chat Assistant</h1>
        <p>Powered by Amazon Bedrock</p>
        <div className="session-info">
          <span>Session: {sessionId.substring(0, 8)}...</span>
          <button className="new-session-btn" onClick={startNewSession}>
            New Session
          </button>
        </div>
      </div>

      {error && <div className="error-message">{error}</div>}

      <div className="messages-container">
        {messages.length === 0 && !isLoading && (
          <div className="empty-state">
            <h3>No messages yet</h3>
            <p>Start a conversation by typing a message below</p>
          </div>
        )}

        {messages.map((msg) => (
          <div key={msg.message_id} className={`message ${msg.role}`}>
            <div className="message-content">
              {formatContent(msg.content)}
              {msg.metadata && msg.role === "assistant" && (
                <div className="message-metadata">
                  {msg.metadata.latency_ms && (
                    <span>⚡ {msg.metadata.latency_ms}ms</span>
                  )}
                  {msg.metadata.output_tokens && (
                    <span> • 📝 {msg.metadata.output_tokens} tokens</span>
                  )}
                </div>
              )}
            </div>
          </div>
        ))}

        {isLoading && (
          <div className="message assistant">
            <div className="loading-indicator">
              <div className="loading-dot"></div>
              <div className="loading-dot"></div>
              <div className="loading-dot"></div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      <div className="input-container">
        <form onSubmit={sendMessage} className="input-wrapper">
          <input
            type="text"
            className="message-input"
            placeholder="Type your message..."
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            disabled={isLoading}
          />
          <button
            type="submit"
            className="send-button"
            disabled={isLoading || !inputValue.trim()}
          >
            {isLoading ? "Sending..." : "Send"}
          </button>
        </form>
      </div>
    </div>
  );
};

const root = createRoot(document.getElementById("root"));
root.render(<App />);
