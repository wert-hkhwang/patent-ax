"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PerspectiveTabs, PerspectiveSummary } from "../patent/PerspectiveTabs";

// 백엔드 API URL (프록시 사용)
const API_URL = process.env.NEXT_PUBLIC_API_URL || "/api";

interface Message {
  role: "user" | "assistant";
  content: string;
  perspectiveSummary?: PerspectiveSummary;  // Phase 104: 관점별 요약
}

interface EasyChatProps {
  selectedQuestion: string;
  onQuestionSent: () => void;
}

export function EasyChat({ selectedQuestion, onQuestionSent }: EasyChatProps) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // 자동 스크롤
  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // 선택된 질문이 변경되면 자동으로 전송
  useEffect(() => {
    if (selectedQuestion) {
      setInput(selectedQuestion);
      // 약간의 딜레이 후 자동 전송
      setTimeout(() => {
        sendMessage(selectedQuestion);
        onQuestionSent();
      }, 100);
    }
  }, [selectedQuestion]);

  const sendMessage = useCallback(async (content: string) => {
    if (!content.trim() || isLoading) return;

    // 사용자 메시지 추가
    const userMessage: Message = { role: "user", content };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);

    // 어시스턴트 빈 메시지 추가 (스트리밍용)
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

    try {
      // L1 레벨로 요청
      const requestBody = {
        query: content,
        session_id: "easy_mode",
        level: "L1", // 초등학생 레벨
      };

      const response = await fetch(`${API_URL}/workflow/chat/stream`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(requestBody),
      });

      if (!response.ok) {
        throw new Error(`API 오류: ${response.status}`);
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();

      if (!reader) {
        throw new Error("응답을 읽을 수 없습니다");
      }

      let accumulatedText = "";
      let currentEvent = "";
      let perspectiveSummaryData: PerspectiveSummary | undefined;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value);
        const lines = chunk.split("\n");

        for (const line of lines) {
          // event: 라인 처리
          if (line.startsWith("event: ")) {
            currentEvent = line.slice(7).trim();
            continue;
          }

          // data: 라인 처리
          if (line.startsWith("data: ")) {
            const data = line.slice(6);
            if (data === "[DONE]") continue;

            // text 이벤트의 경우 직접 텍스트로 처리
            if (currentEvent === "text") {
              // 이스케이프된 \n을 실제 줄바꿈으로 변환
              const textContent = data.replace(/\\n/g, "\n");
              accumulatedText += textContent;
              setMessages((prev) => {
                const newMessages = [...prev];
                newMessages[newMessages.length - 1] = {
                  role: "assistant",
                  content: accumulatedText,
                  perspectiveSummary: perspectiveSummaryData,
                };
                return newMessages;
              });
            }

            // Phase 104: perspective_summary 이벤트 처리
            if (currentEvent === "perspective_summary") {
              try {
                const parsedData = JSON.parse(data);
                if (parsedData.purpose && parsedData.material && parsedData.method && parsedData.effect) {
                  perspectiveSummaryData = parsedData as PerspectiveSummary;
                  // 관점별 요약이 도착하면 메시지 업데이트
                  setMessages((prev) => {
                    const newMessages = [...prev];
                    newMessages[newMessages.length - 1] = {
                      ...newMessages[newMessages.length - 1],
                      perspectiveSummary: perspectiveSummaryData,
                    };
                    return newMessages;
                  });
                  console.log("Phase 104: 관점별 요약 수신:", perspectiveSummaryData);
                }
              } catch (e) {
                console.error("perspective_summary 파싱 오류:", e);
              }
            }

            currentEvent = ""; // 이벤트 초기화
          }
        }
      }
    } catch (error) {
      console.error("메시지 전송 오류:", error);
      setMessages((prev) => {
        const newMessages = [...prev];
        newMessages[newMessages.length - 1] = {
          role: "assistant",
          content: "앗! 오류가 생겼어요. 다시 한번 물어봐 주세요! 😅",
        };
        return newMessages;
      });
    } finally {
      setIsLoading(false);
      inputRef.current?.focus();
    }
  }, [isLoading]);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    sendMessage(input);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  };

  return (
    <div className="h-full flex flex-col">
      {/* 메시지 영역 */}
      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        {messages.length === 0 ? (
          <div className="flex items-center justify-center h-full">
            <div className="text-center">
              <div className="text-6xl mb-4">🎯</div>
              <h2 className="text-3xl font-bold text-gray-700 mb-2">
                무엇이 궁금한가요?
              </h2>
              <p className="text-xl text-gray-500">
                위의 버튼을 눌러보거나 직접 질문해보세요!
              </p>
            </div>
          </div>
        ) : (
          messages.map((message, index) => (
            <div
              key={index}
              className={`flex ${
                message.role === "user" ? "justify-end" : "justify-start"
              }`}
            >
              <div
                className={`max-w-[80%] rounded-2xl p-4 shadow-lg ${
                  message.role === "user"
                    ? "bg-gradient-to-br from-blue-500 to-purple-500 text-white"
                    : "bg-white text-gray-800 border-2 border-gray-100"
                }`}
              >
                {message.role === "assistant" ? (
                  <div className="space-y-4">
                    {/* Phase 104: 관점별 요약 탭 (있는 경우) */}
                    {message.perspectiveSummary && (
                      <PerspectiveTabs
                        summary={message.perspectiveSummary}
                        level="L1"
                        className="mb-4"
                      />
                    )}

                    {/* 기존 마크다운 응답 */}
                    <div className="prose prose-lg max-w-none">
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={{
                          p: ({ children }) => (
                            <p className="text-xl leading-relaxed mb-3">
                              {children}
                            </p>
                          ),
                          strong: ({ children }) => (
                            <strong className="font-bold text-blue-600">
                              {children}
                            </strong>
                          ),
                          ul: ({ children }) => (
                            <ul className="list-disc list-inside space-y-2 text-lg">
                              {children}
                            </ul>
                          ),
                          li: ({ children }) => (
                            <li className="ml-4">{children}</li>
                          ),
                        }}
                      >
                        {message.content}
                      </ReactMarkdown>
                    </div>
                  </div>
                ) : (
                  <p className="text-xl">{message.content}</p>
                )}
              </div>
            </div>
          ))
        )}

        {isLoading && messages[messages.length - 1]?.content === "" && (
          <div className="flex justify-start">
            <div className="bg-white rounded-2xl p-4 shadow-lg border-2 border-gray-100">
              <div className="flex items-center gap-2">
                <div className="animate-bounce text-2xl">💭</div>
                <span className="text-xl text-gray-600">생각하는 중...</span>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* 입력 영역 */}
      <div className="border-t-2 border-gray-100 p-6 bg-gray-50">
        <form onSubmit={handleSubmit} className="flex gap-3">
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="여기에 질문을 입력하세요..."
            className="flex-1 px-6 py-4 text-xl border-2 border-gray-300 rounded-2xl focus:outline-none focus:ring-4 focus:ring-blue-300 focus:border-blue-400 resize-none"
            rows={2}
            disabled={isLoading}
          />
          <button
            type="submit"
            disabled={!input.trim() || isLoading}
            className="px-8 py-4 bg-gradient-to-br from-blue-500 to-purple-500 text-white text-xl font-bold rounded-2xl hover:from-blue-600 hover:to-purple-600 disabled:from-gray-300 disabled:to-gray-400 transition-all transform hover:scale-105 active:scale-95 shadow-lg disabled:shadow-none"
          >
            {isLoading ? "⏳" : "보내기 🚀"}
          </button>
        </form>

        <p className="text-center text-gray-500 mt-3 text-sm">
          Shift + Enter로 줄바꿈, Enter로 전송
        </p>
      </div>
    </div>
  );
}
