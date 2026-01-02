'use client';

import { useEffect, useState } from 'react';
import { supabase } from '@/lib/supabase';
import { PageLayout } from '@/components/ui/PageLayout';
import Link from 'next/link';
import { ChevronRight, Search } from 'lucide-react';
import { ChevronLeft } from 'lucide-react';

export default function ExercisesListPage() {
    const [exercises, setExercises] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [query, setQuery] = useState('');

    useEffect(() => {
        async function fetchExercises() {
            const { data } = await supabase.from('exercises').select('*').order('name');
            setExercises(data || []);
            setLoading(false);
        }
        fetchExercises();
    }, []);

    const filtered = exercises.filter(e => e.name.toLowerCase().includes(query.toLowerCase()));

    return (
        <PageLayout
            title="Analytics"
            action={
                <Link href="/progress" className="p-2 -mr-2 text-muted-foreground hover:text-foreground">
                    <ChevronLeft size={24} />
                </Link>
            }
        >
            <div className="relative mb-4">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" size={16} />
                <input
                    type="text"
                    placeholder="Filter exercises..."
                    className="w-full bg-secondary rounded-xl py-2 pl-9 pr-4 text-sm"
                    value={query}
                    onChange={e => setQuery(e.target.value)}
                />
            </div>

            <div className="space-y-2">
                {loading ? <div className="text-center py-10 text-muted-foreground animate-pulse">Loading...</div> :
                    filtered.map(ex => (
                        <Link
                            key={ex.id}
                            href={`/progress/exercises/${ex.id}`}
                            className="flex items-center justify-between p-4 bg-card border border-border rounded-xl hover:border-primary transition-colors group"
                        >
                            <span className="font-semibold">{ex.name}</span>
                            <ChevronRight size={16} className="text-muted-foreground group-hover:text-primary transition-colors" />
                        </Link>
                    ))}
            </div>
        </PageLayout>
    );
}
