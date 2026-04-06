export interface Template {
    id: string;
    owner_user_id: string;
    type: 'workout' | 'program';
    name: string;
    description: string | null;
    created_at: string;
}

export interface TemplateVersion {
    id: string;
    template_id: string;
    version_number: number;
    is_live: boolean;
    created_at: string;
}

// Ensure this matches your existing types/index.ts plus additions
export interface ProgramDay {
    id: string;
    template_version_id: string;
    day_index: number; // 1-7
    label: string;
    workout_template_id: string | null;
    // Joins
    workout_template?: Template;
}

export interface UserTemplateLibrary {
    id: string;
    user_id: string;
    template_id: string;
    pinned_template_version_id: string;
    added_at: string;
    // Joins
    template?: Template;
    pinned_version?: TemplateVersion;
}

export interface Exercise {
    id: string;
    name: string;
    variation_group_id: string | null;
    primary_muscle_id: string | null;
    created_by_user_id: string | null;
    is_global: boolean;
}

export interface WorkoutSession {
    id: string;
    user_id: string;
    template_id: string | null;
    template_version_id: string | null;
    started_at: string;
    ended_at: string | null;
    notes: string | null;
}
