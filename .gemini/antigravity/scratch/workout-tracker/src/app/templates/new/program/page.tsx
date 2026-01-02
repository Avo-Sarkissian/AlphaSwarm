'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { ChevronLeft, Save, Calendar, Dumbbell, X } from 'lucide-react';
import Link from 'next/link';
import { PageLayout } from '@/components/ui/PageLayout';
import { supabase } from '@/lib/supabase';
import { DEV_USER_ID } from '@/lib/constants';
import type { Template, UserTemplateLibrary } from '@/types';
import { cn } from '@/lib/utils';

// Helper for days
const DAYS = [
    { index: 1, label: 'Mon' },
    { index: 2, label: 'Tue' },
    { index: 3, label: 'Wed' },
    { index: 4, label: 'Thu' },
    { index: 5, label: 'Fri' },
    { index: 6, label: 'Sat' },
    { index: 7, label: 'Sun' },
];

interface DayDraft {
    day_index: number;
    label: string;
    workout_template_id: string | null;
    workout_name?: string; // Optimistic helper
}

export default function CreateProgramTemplatePage() {
    const router = useRouter();
    const [name, setName] = useState('');
    const [description, setDescription] = useState('');
    const [days, setDays] = useState<DayDraft[]>(
        DAYS.map(d => ({ day_index: d.index, label: d.label, workout_template_id: null }))
    );

    const [showWorkoutSelector, setShowWorkoutSelector] = useState<{ dayIndex: number } | null>(null);
    const [availableWorkouts, setAvailableWorkouts] = useState<Template[]>([]);
    const [saving, setSaving] = useState(false);

    // Fetch available workout templates on mount (filtered to pinned for now, or all owned?)
    // Requirement: "user's pinned workout templates OR all available"
    // Let's fetch pinned ones for simplicity and better UX first.
    useEffect(() => {
        async function fetchWorkouts() {
            const { data } = await supabase
                .from('user_template_library')
                .select('*, template:templates(*)')
                .eq('user_id', DEV_USER_ID);

            if (data) {
                // Filter only workout types
                const workouts = data
                    .map(d => d.template)
                    .filter(t => t?.type === 'workout') as Template[];
                setAvailableWorkouts(workouts);
            }
        }
        fetchWorkouts();
    }, []);

    const handleSelectWorkout = (template: Template) => {
        if (!showWorkoutSelector) return;

        setDays(prev => prev.map(d => {
            if (d.day_index === showWorkoutSelector.dayIndex) {
                return { ...d, workout_template_id: template.id, workout_name: template.name };
            }
            return d;
        }));
        setShowWorkoutSelector(null);
    };

    const handleClearDay = (dayIndex: number, e: React.MouseEvent) => {
        e.stopPropagation();
        setDays(prev => prev.map(d => {
            if (d.day_index === dayIndex) {
                return { ...d, workout_template_id: null, workout_name: undefined };
            }
            return d;
        }));
    };

    const handleSave = async () => {
        if (!name.trim()) return;
        setSaving(true);

        try {
            // 1. Create Template
            const { data: templateData, error: templateError } = await supabase
                .from('templates')
                .insert({
                    owner_user_id: DEV_USER_ID,
                    type: 'program',
                    name,
                    description
                })
                .select()
                .single();

            if (templateError || !templateData) throw templateError;

            // 2. Create Version 1
            const { data: versionData, error: versionError } = await supabase
                .from('template_versions')
                .insert({
                    template_id: templateData.id,
                    version_number: 1,
                    is_live: true
                })
                .select()
                .single();

            if (versionError || !versionData) throw versionError;

            // 3. Pin to Library
            await supabase.from('user_template_library').insert({
                user_id: DEV_USER_ID,
                template_id: templateData.id,
                pinned_template_version_id: versionData.id
            });

            // 4. Insert Program Days
            // Only insert relevant info
            const daysPayload = days.map(d => ({
                template_version_id: versionData.id,
                day_index: d.day_index,
                label: d.label, // Users could edit this label in v2
                workout_template_id: d.workout_template_id
            }));

            const { error: daysError } = await supabase.from('program_days').insert(daysPayload);
            if (daysError) throw daysError;

            router.push('/templates');

        } catch (err) {
            console.error('Error saving program:', err);
            alert('Failed to save program');
        } finally {
            setSaving(false);
        }
    };

    return (
        <PageLayout
            title="Create Program"
            action={
                <Link href="/templates/new" className="p-2 -mr-2 text-muted-foreground hover:text-foreground">
                    <ChevronLeft size={24} />
                </Link>
            }
        >
            <div className="space-y-6 pb-24">
                <div className="space-y-4">
                    <div>
                        <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider ml-1">Program Name</label>
                        <input
                            type="text"
                            placeholder="e.g. 4-Day Split"
                            className="w-full bg-card border border-border rounded-xl px-4 py-3 mt-1 text-lg font-semibold focus:border-primary transition-colors"
                            value={name}
                            onChange={e => setName(e.target.value)}
                        />
                    </div>
                    <div>
                        <label className="text-xs font-semibold text-muted-foreground uppercase tracking-wider ml-1">Description</label>
                        <textarea
                            placeholder="Optional notes..."
                            className="w-full bg-card border border-border rounded-xl px-4 py-3 mt-1 text-sm focus:border-primary transition-colors min-h-[80px]"
                            value={description}
                            onChange={e => setDescription(e.target.value)}
                        />
                    </div>
                </div>

                <div>
                    <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3 ml-1">Weekly Schedule</h3>
                    <div className="grid gap-3">
                        {days.map((day) => (
                            <button
                                key={day.day_index}
                                onClick={() => setShowWorkoutSelector({ dayIndex: day.day_index })}
                                className="flex items-center gap-4 p-4 bg-card border border-border rounded-xl hover:border-primary transition-all text-left group"
                            >
                                <div className="w-10 flex flex-col items-center justify-center">
                                    <span className="text-xs font-bold text-muted-foreground uppercase">{day.label}</span>
                                </div>
                                <div className="flex-1 border-l border-border pl-4">
                                    {day.workout_template_id ? (
                                        <div>
                                            <span className="font-semibold text-primary">{day.workout_name}</span>
                                            <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Workout Assigned</p>
                                        </div>
                                    ) : (
                                        <span className="text-muted-foreground/50 text-sm font-medium italic">Rest Day</span>
                                    )}
                                </div>
                                {day.workout_template_id ? (
                                    <div
                                        onClick={(e) => handleClearDay(day.day_index, e)}
                                        className="p-2 text-muted-foreground hover:text-destructive transition-colors"
                                    >
                                        <X size={16} />
                                    </div>
                                ) : (
                                    <div className="p-2 text-muted-foreground/30 group-hover:text-primary transition-colors">
                                        <Dumbbell size={16} />
                                    </div>
                                )}
                            </button>
                        ))}
                    </div>
                </div>

                <button
                    onClick={handleSave}
                    disabled={!name.trim() || saving}
                    className={cn(
                        "fixed bottom-20 left-4 right-4 max-w-md mx-auto h-14 rounded-full font-bold text-lg shadow-lg flex items-center justify-center gap-2 transition-all",
                        !name.trim()
                            ? "bg-secondary text-muted-foreground cursor-not-allowed"
                            : "bg-primary text-primary-foreground hover:scale-[1.02] active:scale-[0.98]"
                    )}
                >
                    {saving ? 'Saving...' : <><Save size={20} /> Save Program</>}
                </button>
            </div>

            {/* Workout Selector Modal */}
            {showWorkoutSelector && (
                <div className="fixed inset-0 z-[60] bg-background/95 backdrop-blur-sm animate-in fade-in duration-200 p-4 flex flex-col">
                    <div className="flex justify-between items-center mb-6">
                        <h2 className="text-lg font-bold">Select Workout</h2>
                        <button onClick={() => setShowWorkoutSelector(null)} className="p-2 bg-secondary rounded-full">
                            <X size={20} />
                        </button>
                    </div>

                    <div className="flex-1 overflow-y-auto space-y-3">
                        {availableWorkouts.length === 0 ? (
                            <div className="text-center py-10 text-muted-foreground">
                                No workouts found in your library. <br />
                                <Link href="/templates/new/workout" className="text-primary underline">Create one first</Link>.
                            </div>
                        ) : (
                            availableWorkouts.map(w => (
                                <button
                                    key={w.id}
                                    onClick={() => handleSelectWorkout(w)}
                                    className="w-full text-left p-4 bg-card border border-border rounded-xl hover:border-primary transition-colors"
                                >
                                    <h4 className="font-semibold">{w.name}</h4>
                                    <p className="text-xs text-muted-foreground">{w.description || 'No description'}</p>
                                </button>
                            ))
                        )}
                    </div>
                </div>
            )}

        </PageLayout>
    );
}
