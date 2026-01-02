'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import { Play, Dumbbell, History, ChevronRight } from 'lucide-react';
import { PageLayout } from '@/components/ui/PageLayout';
import { supabase } from '@/lib/supabase';
import { DEV_USER_ID } from '@/lib/constants';
import type { UserTemplateLibrary } from '@/types';

export default function TrainPage() {
    const router = useRouter();
    const [pinned, setPinned] = useState<UserTemplateLibrary[]>([]);
    const [loading, setLoading] = useState(true);
    const [starting, setStarting] = useState<string | null>(null);

    useEffect(() => {
        // Check for active session first? 
        // For v1, we assume no active session persistence across refreshes on this screen, 
        // but we could look for open sessions.

        async function fetchPinned() {
            const { data } = await supabase
                .from('user_template_library')
                .select('*, template:templates(*), pinned_version:template_versions(*)')
                .eq('user_id', DEV_USER_ID)
                .order('added_at', { ascending: false });

            if (data) setPinned(data);
            setLoading(false);
        }
        fetchPinned();
    }, []);

    const handleStartSession = async (templateLibId: string) => {
        const templateLib = pinned.find(p => p.id === templateLibId);
        if (!templateLib) return;

        setStarting(templateLibId);
        try {
            let workoutTemplateId = templateLib.template_id;
            let workoutVersionId = templateLib.pinned_template_version_id;

            // A) Handling PROGRAM Resolution
            if (templateLib.template?.type === 'program') {
                const dayIndex = new Date().getDay() || 7; // Sunday is 0 -> mapped to 7, else 1-6 Mon-Sat

                // Fetch Program Day
                const { data: programDay } = await supabase
                    .from('program_days')
                    .select('*')
                    .eq('template_version_id', templateLib.pinned_template_version_id)
                    .eq('day_index', dayIndex)
                    .single();

                if (!programDay || !programDay.workout_template_id) {
                    alert('No workout scheduled for today in this program.');
                    setStarting(null);
                    return;
                }

                // Resolve Workout Template Version
                workoutTemplateId = programDay.workout_template_id;

                // Check if user has this workout pinned, use that version
                const { data: pinnedWorkout } = await supabase
                    .from('user_template_library')
                    .select('pinned_template_version_id')
                    .eq('user_id', DEV_USER_ID)
                    .eq('template_id', workoutTemplateId)
                    .single();

                if (pinnedWorkout) {
                    workoutVersionId = pinnedWorkout.pinned_template_version_id;
                } else {
                    // Otherwise fetch LIVE version & Pin It (Auto-Pin Logic)
                    const { data: liveVersion } = await supabase
                        .from('template_versions')
                        .select('id')
                        .eq('template_id', workoutTemplateId)
                        .eq('is_live', true)
                        .single();

                    if (liveVersion) {
                        workoutVersionId = liveVersion.id;
                        // Pin it
                        await supabase.from('user_template_library').insert({
                            user_id: DEV_USER_ID,
                            template_id: workoutTemplateId,
                            pinned_template_version_id: liveVersion.id
                        });
                    }
                }
            }

            // 1. Create Session
            const { data: session, error: sessionError } = await supabase
                .from('workout_sessions')
                .insert({
                    user_id: DEV_USER_ID,
                    template_id: workoutTemplateId,
                    template_version_id: workoutVersionId,
                    started_at: new Date().toISOString()
                })
                .select()
                .single();

            if (sessionError || !session) throw sessionError;

            // 2. Resolve Template Items (Snapshot)
            const { data: items } = await supabase
                .from('workout_template_items')
                .select('*')
                .eq('template_version_id', workoutVersionId)
                .order('order_index');

            if (items) {
                // TODO: Handle Conditional Blocks (resolve block_ref)
                let sessionExercisesPayload = [];
                let orderCounter = 0;

                for (const item of items) {
                    if (item.item_type === 'exercise' && item.exercise_id) {
                        sessionExercisesPayload.push({
                            session_id: session.id,
                            exercise_id: item.exercise_id,
                            order_index: orderCounter++,
                            source: 'template'
                        });
                    }
                }

                if (sessionExercisesPayload.length > 0) {
                    const { data: insertedExercises, error: exError } = await supabase
                        .from('session_exercises')
                        .insert(sessionExercisesPayload)
                        .select();

                    if (exError) throw exError;

                    // 3. Create Default Sets
                    if (insertedExercises) {
                        let setsPayload = [];
                        for (const sex of insertedExercises) {
                            const original = items.find(i => i.exercise_id === sex.exercise_id);
                            const setBody = {
                                session_exercise_id: sex.id,
                                weight: 0,
                                reps: original?.default_reps || 8
                            };

                            const count = original?.default_sets || 3;
                            for (let i = 0; i < count; i++) {
                                setsPayload.push({ ...setBody, set_index: i });
                            }
                        }
                        if (setsPayload.length > 0) {
                            await supabase.from('session_sets').insert(setsPayload);
                        }
                    }
                }
            }

            router.push(`/train/session/${session.id}`);

        } catch (err) {
            console.error('Start session error:', err);
            setStarting(null);
        }
    };

    return (
        <PageLayout title="Train">
            <div className="space-y-6">
                <section>
                    <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">Quick Start</h2>
                    <button
                        onClick={() => {/* TODO: Empty Session */ }}
                        className="w-full bg-card border border-border p-4 rounded-xl flex items-center gap-4 hover:border-primary transition-colors text-left"
                    >
                        <div className="h-12 w-12 rounded-full bg-primary/10 text-primary flex items-center justify-center">
                            <Play size={24} fill="currentColor" />
                        </div>
                        <div>
                            <h3 className="font-semibold text-foreground">Empty Workout</h3>
                            <p className="text-xs text-muted-foreground">Log a session from scratch</p>
                        </div>
                    </button>
                    {/* Add Debug for current time */}
                    {/* <p className="text-[10px] text-muted-foreground mt-2 font-mono">Server Time: {new Date().toISOString()}</p> */}
                </section>

                <section>
                    <h2 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">From Library</h2>
                    <div className="space-y-3">
                        {loading ? (
                            <div className="text-center text-muted-foreground py-4">Loading templates...</div>
                        ) : pinned.length === 0 ? (
                            <div className="text-muted-foreground text-sm italic">No templates pinned. Go to Templates tab to create one.</div>
                        ) : (
                            pinned.map(pin => (
                                <button
                                    key={pin.id}
                                    onClick={() => handleStartSession(pin.id)}
                                    disabled={starting === pin.id}
                                    className="w-full bg-card border border-border p-4 rounded-xl flex items-center justify-between hover:border-primary transition-colors group text-left"
                                >
                                    <div className="flex items-center gap-4">
                                        <div className="h-10 w-10 rounded-lg bg-secondary flex items-center justify-center text-muted-foreground group-hover:text-foreground group-hover:bg-primary/20 transition-colors">
                                            {pin.template?.type === 'program' ? <CalendarDays size={20} /> : <Dumbbell size={20} />}
                                        </div>
                                        <div>
                                            <h3 className="font-semibold text-foreground">{pin.template?.name}</h3>
                                            <p className="text-xs text-muted-foreground capitalize">
                                                {pin.template?.type} • v{pin.pinned_version?.version_number}
                                            </p>
                                        </div>
                                    </div>
                                    {starting === pin.id ? (
                                        <span className="text-xs text-primary animate-pulse">Starting...</span>
                                    ) : (
                                        <ChevronRight size={16} className="text-muted-foreground group-hover:translate-x-1 transition-transform" />
                                    )}
                                </button>
                            ))
                        )}
                    </div>
                </section>
            </div>
        </PageLayout>
    );
}
