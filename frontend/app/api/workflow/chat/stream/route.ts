/**
 * SSE Proxy API Route
 *
 * Next.js rewrites는 SSE 스트리밍을 제대로 프록시하지 못하므로
 * 직접 API Route로 SSE를 프록시합니다.
 */

import { NextRequest } from "next/server";

// 백엔드 서버 URL (서버 사이드에서는 localhost 사용)
const BACKEND_URL = "http://localhost:8000";

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    // 백엔드로 요청 전달
    const backendResponse = await fetch(`${BACKEND_URL}/workflow/chat/stream`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });

    if (!backendResponse.ok) {
      return new Response(
        JSON.stringify({ error: `Backend error: ${backendResponse.status}` }),
        { status: backendResponse.status, headers: { "Content-Type": "application/json" } }
      );
    }

    // SSE 스트림 프록시
    const reader = backendResponse.body?.getReader();
    if (!reader) {
      return new Response(
        JSON.stringify({ error: "No response body" }),
        { status: 500, headers: { "Content-Type": "application/json" } }
      );
    }

    // ReadableStream으로 SSE 전달
    const stream = new ReadableStream({
      async start(controller) {
        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            controller.enqueue(value);
          }
        } catch (error) {
          console.error("Stream error:", error);
        } finally {
          controller.close();
          reader.releaseLock();
        }
      },
    });

    return new Response(stream, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
      },
    });
  } catch (error) {
    console.error("Proxy error:", error);
    return new Response(
      JSON.stringify({ error: "Internal server error" }),
      { status: 500, headers: { "Content-Type": "application/json" } }
    );
  }
}
