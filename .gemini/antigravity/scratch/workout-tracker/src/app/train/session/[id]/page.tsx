'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import { PageLayout } from '@/components/ui/PageLayout';
import { supabase } from '@/lib/supabase';
import { ExerciseLogger } from '@/components/train/ExerciseLogger';
import { ArrowLeft, CheckCircle2 } from 'lucide-react';
import Link from 'next/link';

export default function SessionPage() {
    const { id } = useParams();
    const router = useRouter();
    const [exercises, setExercises] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        async function fetchSession() {
            const { data: sessionExercises } = await supabase
                .from('session_exercises')
                .select(`
          *,
          exercise:exercises(name),
          sets:session_sets(*)
        `)
                .eq('session_id', id)
                .order('order_index');

            if (sessionExercises) {
                // Sort sets by index
                const processed = sessionExercises.map(ex => ({
                    ...ex,
                    sets: ex.sets.sort((a: any, b: any) => a.set_index - b.set_index)
                }));
                setExercises(processed);
            }
            setLoading(false);
        }
        fetchSession();
    }, [id]);

    const finishWorkout = async () => {
        if (confirm('Finish workout?')) {
            await supabase
                .from('workout_sessions')
                .update({ ended_at: new Date().toISOString() })
                .eq('id', id);
            router.push('/progress');
        }
    };

    if (loading) return <div className="p-8 text-center animate-pulse">Loading session...</div>;

    return (
        <div className="min-h-screen bg-background pb-32">
            <header className="sticky top-0 z-40 bg-background/80 backdrop-blur-md border-b border-border px-4 py-4 flex items-center justify-between">
                <Link href="/train">
                    <ArrowLeft className="text-muted-foreground" />
                </Link>
                <h1 className="font-bold">Live Session</h1>
                <button
                    onClick={finishWorkout}
                    className="bg-primary text-primary-foreground text-xs font-bold px-3 py-1.5 rounded-full"
                >
                    FINISH
                </button>
            </header>

            <div className="p-4">
                {exercises.map(ex => (
                    <ExerciseLogger
                        key={ex.id}
                        sessionExerciseId={ex.id}
                        exerciseName={ex.exercise.name}
                        initialSets={ex.sets}
                    />
                ))}
            </div>
        </div>
    );
}
