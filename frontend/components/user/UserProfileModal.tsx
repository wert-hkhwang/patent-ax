"use client";

import { UserProfileForm } from "./UserProfileForm";

interface UserProfile {
  id: number;
  user_id: string;
  education_level: string | null;
  occupation: string | null;
  registered_level: string;
  current_level: string;
  level_description: string;
}

interface UserProfileModalProps {
  isOpen: boolean;
  onClose: () => void;
  onProfileCreated: (profile: UserProfile) => void;
}

export function UserProfileModal({ isOpen, onClose, onProfileCreated }: UserProfileModalProps) {
  if (!isOpen) return null;

  const handleProfileCreated = (profile: UserProfile) => {
    onProfileCreated(profile);
    onClose();
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
      {/* 배경 오버레이 */}
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* 모달 컨텐츠 */}
      <div className="relative z-10 max-w-2xl w-full">
        <UserProfileForm
          onProfileCreated={handleProfileCreated}
          onCancel={onClose}
        />
      </div>
    </div>
  );
}
