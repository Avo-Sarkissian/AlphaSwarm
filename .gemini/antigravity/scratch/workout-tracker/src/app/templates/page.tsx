'use client';

import { useEffect, useState } from 'react';
import { Plus, ChevronRight, FileDigit } from 'lucide-react';
import Link from 'next/link';
import { PageLayout } from '@/components/ui/PageLayout';
import { supabase } from '@/lib/supabase';
import { DEV_USER_ID } from '@/lib/constants';
import type { UserTemplateLibrary } from '@/types';

export default function TemplatesPage() {
    const [library, setLibrary] = useState<UserTemplateLibrary[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        async function fetchLibrary() {
            try {
                const { data, error } = await supabase
                    .from('user_template_library')
                    .select(`
            *,
            template:templates(*),
            pinned_version:template_versions(*)
          `)
                    .eq('user_id', DEV_USER_ID)
                    .order('added_at', { ascending: false });

                if (error) {
                    console.error('Error fetching templates:', error);
                    // Fallback mock data if DB not connected
                    setLibrary([]);
                } else {
                    setLibrary(data || []);
                }
            } catch (err) {
                console.error('Exception fetching templates:', err);
            } finally {
                setLoading(false);
            }
        }

        fetchLibrary();
    }, []);

    return (
        <PageLayout
            title="Templates"
            action={
                <Link
                    href="/templates/new"
                    className="p-2 bg-primary text-primary-foreground rounded-full hover:bg-primary/90 transition"
                >
                    <Plus size={20} />
                </Link>
            }
        >
            <div className="space-y-4">
                {loading ? (
                    <div className="text-center py-10 text-muted-foreground animate-pulse">Loading library...</div>
                ) : library.length === 0 ? (
                    <div className="text-center py-10 border border-dashed border-border rounded-lg">
                        <p className="text-muted-foreground mb-4">No templates pinned yet.</p>
                        <Link
                            href="/templates/new"
                            className="inline-flex items-center text-sm font-medium text-primary hover:underline"
                        >
                            Create your first template
                        </Link>
                    </div>
                ) : (
                    library.map((item) => (
                        <Link
                            key={item.id}
                            href={`/templates/${item.template_id}`}
                            className="block group"
                        >
                            <div className="bg-card border border-border rounded-xl p-4 flex items-center justify-between group-active:scale-[0.98] transition-transform">
                                <div className="flex items-center gap-4">
                                    <div className="h-10 w-10 rounded-lg bg-secondary flex items-center justify-center text-secondary-foreground">
                                        <FileDigit size={20} />
                                    </div>
                                    <div>
                                        <h3 className="font-semibold text-foreground">{item.template?.name || 'Unknown Template'}</h3>
                                        <p className="text-xs text-muted-foreground line-clamp-1">
                                            {item.template?.description || 'No description'}
                                        </p>
                                        <div className="flex gap-2 mt-1">
                                            <span className="text-[10px] uppercase tracking-wider bg-secondary/50 px-1.5 py-0.5 rounded text-muted-foreground">
                                                {item.template?.type}
                                            </span>
                                            <span className="text-[10px] text-muted-foreground py-0.5">
                                                v{item.pinned_version?.version_number}
                                            </span>
                                        </div>
                                    </div>
                                </div>
                                <ChevronRight size={16} className="text-muted-foreground/50 group-hover:text-primary transition-colors" />
                            </div>
                        </Link>
                    ))
                )}
            </div>
        </PageLayout>
    );
}
