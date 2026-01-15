"use client";

interface UserProfile {
  id: number;
  user_id: string;
  education_level: string | null;
  occupation: string | null;
  registered_level: string;
  current_level: string;
  level_description: string;
}

interface UserProfileDisplayProps {
  profile: UserProfile | null;
  onCreateProfile: () => void;
}

const levelEmojis: Record<string, string> = {
  "L1": "🎓",
  "L2": "📚",
  "L3": "💼",
  "L4": "🔬",
  "L5": "⚖️",
  "L6": "📊",
};

export function UserProfileDisplay({ profile, onCreateProfile }: UserProfileDisplayProps) {
  if (!profile) {
    return (
      <button
        onClick={onCreateProfile}
        className="px-4 py-2 bg-green-500 hover:bg-green-600 text-white font-bold rounded-lg transition-colors flex items-center gap-2"
      >
        <span>👤</span>
        프로필 생성
      </button>
    );
  }

  return (
    <div className="flex items-center gap-3 bg-white/10 rounded-lg px-4 py-2">
      <div className="text-2xl">
        {levelEmojis[profile.current_level] || "👤"}
      </div>
      <div className="text-sm">
        <div className="font-bold text-white">{profile.user_id}</div>
        <div className="text-blue-100">
          {profile.current_level} - {profile.level_description}
        </div>
      </div>
    </div>
  );
}
