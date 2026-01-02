'use client';

import { PageLayout } from '@/components/ui/PageLayout';
import { supabase } from '@/lib/supabase';
import { DEV_USER_ID } from '@/lib/constants';
import { useEffect, useState } from 'react';
import { Trophy, TrendingUp, Calendar } from 'lucide-react';
import Link from 'next/link';

export default function ProgressPage() {
    const [stats, setStats] = useState({ sessions: 0, volume: 0, prs: 0 });
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        async function fetchStats() {
            // Mock for now or simple query
            const { count } = await supabase.from('workout_sessions')
                .select('*', { count: 'exact', head: true })
                .eq('user_id', DEV_USER_ID);

            setStats({ sessions: count || 0, volume: 125000, prs: 3 }); // Mock volume/PRs for V1 display
            setLoading(false);
        }
        fetchStats();
    }, []);

    return (
        <PageLayout title="Progress">
            <div className="grid grid-cols-3 gap-4 mb-8">
                <div className="bg-card border border-border rounded-xl p-4 flex flex-col items-center justify-center text-center">
                    <Calendar className="text-primary mb-2" size={20} />
                    <span className="text-2xl font-bold">{stats.sessions}</span>
                    <span className="text-[10px] uppercase text-muted-foreground tracking-wide">Sessions</span>
                </div>
                <div className="bg-card border border-border rounded-xl p-4 flex flex-col items-center justify-center text-center">
                    <TrendingUp className="text-emerald-500 mb-2" size={20} />
                    <span className="text-2xl font-bold">125k</span>
                    <span className="text-[10px] uppercase text-muted-foreground tracking-wide">Vol (lb)</span>
                </div>
                <div className="bg-card border border-border rounded-xl p-4 flex flex-col items-center justify-center text-center">
                    <Trophy className="text-amber-500 mb-2" size={20} />
                    <span className="text-2xl font-bold">{stats.prs}</span>
                    <span className="text-[10px] uppercase text-muted-foreground tracking-wide">PRs</span>
                </div>
            </div>

            <section>
                <div className="flex items-center justify-between mb-4">
                    <h2 className="font-semibold text-lg">Detailed Analytics</h2>
                </div>
                <div className="space-y-3">
                    <Link href="/progress/exercises" className="block bg-card border border-border p-4 rounded-xl hover:border-primary transition-colors">
                        <h3 className="font-semibold">Exercise History</h3>
                        <p className="text-sm text-muted-foreground">View E1RM trends and maxes per lift</p>
                    </Link>
                    <div className="block bg-card border border-border p-4 rounded-xl opacity-50">
                        <h3 className="font-semibold">Muscle Split</h3>
                        <p className="text-sm text-muted-foreground">Weekly volume per muscle group (Coming soon)</p>
                    </div>
                </div>
            </section>
        </PageLayout>
    );
}
