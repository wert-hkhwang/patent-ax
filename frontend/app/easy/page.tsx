"use client";

import { useState } from "react";
import { EasyChat } from "@/components/easy/EasyChat";

/**
 * Easy Mode - 초등학생(L1) 사용자를 위한 쉬운 UI
 *
 * 특징:
 * - 큰 글씨와 친근한 디자인
 * - 추천 질문 버튼
 * - 간단한 검색 인터페이스
 * - 읽기 쉬운 결과 표시
 */
export default function EasyModePage() {
  const [selectedQuestion, setSelectedQuestion] = useState<string>("");

  // 추천 질문 목록
  const suggestedQuestions = [
    {
      emoji: "🔋",
      title: "배터리",
      question: "배터리는 어떻게 만들어지나요?"
    },
    {
      emoji: "🤖",
      title: "로봇",
      question: "로봇은 어떤 기술로 만들어지나요?"
    },
    {
      emoji: "🚗",
      title: "자동차",
      question: "전기 자동차는 어떻게 움직이나요?"
    },
    {
      emoji: "💡",
      title: "발명",
      question: "새로운 발명은 어떻게 하나요?"
    },
    {
      emoji: "🌍",
      title: "환경",
      question: "환경을 지키는 기술은 무엇인가요?"
    },
    {
      emoji: "🎮",
      title: "게임",
      question: "게임은 어떻게 만들어지나요?"
    }
  ];

  const handleQuestionClick = (question: string) => {
    setSelectedQuestion(question);
  };

  return (
    <main className="h-screen flex flex-col bg-gradient-to-br from-blue-50 via-purple-50 to-pink-50">
      {/* 헤더 */}
      <header className="bg-white shadow-lg border-b-4 border-blue-400">
        <div className="max-w-6xl mx-auto p-6 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="text-5xl">🎓</div>
            <div>
              <h1 className="text-3xl font-bold text-blue-600">특허 배움터</h1>
              <p className="text-lg text-gray-600 mt-1">쉽고 재미있게 배워요!</p>
            </div>
          </div>

          <a
            href="/"
            className="px-6 py-3 bg-gray-100 hover:bg-gray-200 text-gray-700 rounded-xl font-bold transition-colors"
          >
            일반 모드로 가기
          </a>
        </div>
      </header>

      {/* 메인 컨텐츠 */}
      <div className="flex-1 overflow-hidden">
        <div className="max-w-6xl mx-auto h-full p-6">
          <div className="bg-white rounded-3xl shadow-2xl h-full flex flex-col overflow-hidden">

            {/* 추천 질문 영역 */}
            <div className="p-6 border-b-2 border-gray-100">
              <h2 className="text-2xl font-bold text-gray-800 mb-4 flex items-center gap-2">
                <span>💭</span>
                궁금한 것을 눌러보세요!
              </h2>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
                {suggestedQuestions.map((item, index) => (
                  <button
                    key={index}
                    onClick={() => handleQuestionClick(item.question)}
                    className="p-4 bg-gradient-to-br from-blue-100 to-purple-100 hover:from-blue-200 hover:to-purple-200 rounded-2xl transition-all transform hover:scale-105 active:scale-95 shadow-lg"
                  >
                    <div className="text-4xl mb-2">{item.emoji}</div>
                    <div className="text-lg font-bold text-gray-800">{item.title}</div>
                  </button>
                ))}
              </div>
            </div>

            {/* 채팅 영역 */}
            <div className="flex-1 overflow-hidden">
              <EasyChat
                selectedQuestion={selectedQuestion}
                onQuestionSent={() => setSelectedQuestion("")}
              />
            </div>

          </div>
        </div>
      </div>

      {/* 푸터 */}
      <footer className="bg-white border-t-4 border-blue-400 p-4 text-center">
        <p className="text-gray-600 text-lg">
          <span className="text-2xl mr-2">✨</span>
          특허청 AI 어시스턴트가 도와드려요!
          <span className="text-2xl ml-2">✨</span>
        </p>
      </footer>
    </main>
  );
}
