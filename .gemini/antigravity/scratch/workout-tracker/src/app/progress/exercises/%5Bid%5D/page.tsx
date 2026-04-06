'use client';

import { useEffect, useState } from 'react';
import { useParams } from 'next/navigation';
import { supabase } from '@/lib/supabase';
import { PageLayout } from '@/components/ui/PageLayout';
import { TrendChart } from '@/components/ui/TrendChart';
import { ChevronLeft } from 'lucide-react';
import Link from 'next/link';

export default function ExerciseDetailPage() {
    const { id } = useParams();
    const [exercise, setExercise] = useState<any>(null);
    const [history, setHistory] = useState<any[]>([]);
    const [chartData, setChartData] = useState<any[]>([]);

    useEffect(() => {
        async function fetchData() {
            // 1. Get Exercise Info
            const { data: ex } = await supabase.from('exercises').select('*').eq('id', id).single();
            setExercise(ex);

            // 2. Get Session History
            // Complex query: Join session_sets -> session_exercises -> workout_sessions
            // For V1, we might need to do client-side assembly or a view if we can't do deep nested filters easily in one go.
            // But we can do: select * from session_exercises where exercise_id = id, include sets, include session(started_at)

            const { data: historyData } = await supabase
                .from('session_exercises')
                .select(`
          *,
          session:workout_sessions(started_at),
          sets:session_sets(*)
        `)
                .eq('exercise_id', id)
                .order('created_at', { ascending: false }); // Latest first

            if (historyData) {
                setHistory(historyData);

                // Compute Chart Data (E1RM over time)
                // E1RM = weight * (1 + reps/30)
                // Take Best E1RM per session
                const points = historyData.map(h => {
                    const bestSet = h.sets.reduce((max: any, set: any) => {
                        const e1rm = set.weight * (1 + set.reps / 30);
                        return e1rm > (max?.e1rm || 0) ? { ...set, e1rm } : max;
                    }, null);

                    if (!bestSet) return null;

                    return {
                        date: h.session?.started_at,
                        value: Math.round(bestSet.e1rm)
                    };
                }).filter(Boolean).reverse(); // Reverse for chart (oldest to newest)

                setChartData(points);
            }
        }
        fetchData();
    }, [id]);

    if (!exercise) return <div className="p-8 text-center">Loading...</div>;

    return (
        <PageLayout
            title={exercise.name}
            action={
                <Link href="/progress/exercises" className="p-2 -mr-2 text-muted-foreground hover:text-foreground">
                    <ChevronLeft size={24} />
                </Link>
            }
        >
            <div className="h-64 bg-card border border-border rounded-xl p-4 mb-6">
                <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">Estimated 1RM Trend</h3>
                <TrendChart data={chartData} />
            </div>

            <div className="space-y-4">
                <h3 className="font-semibold text-lg">History</h3>
                {history.map(h => (
                    <div key={h.id} className="bg-card border border-border p-4 rounded-xl flex justify-between items-center">
                        <div>
                            <div className="text-sm font-semibold text-muted-foreground mb-1">
                                {new Date(h.session?.started_at).toLocaleDateString()}
                            </div>
                            <div className="text-xs text-muted-foreground">
                                {h.sets.length} sets • Max: {Math.max(...h.sets.map((s: any) => s.weight))} lbs
                            </div>
                        </div>
                        <div className="text-right">
                            <div className="text-xl font-bold text-foreground">
                                {(() => {
                                    const best = h.sets.reduce((max: number, s: any) => {
                                        const e1rm = s.weight * (1 + s.reps / 30);
                                        return e1rm > max ? e1rm : max;
                                    }, 0);
                                    return Math.round(best);
                                })()}
                            </div>
                            <div className="text-[10px] text-muted-foreground uppercase">E1RM</div>
                        </div>
                    </div>
                ))}
            </div>
        </PageLayout>
    );
}
