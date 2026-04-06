import type { Metadata } from 'next';
import { Inter } from 'next/font/google';
import './globals.css';
import { BottomNav } from '@/components/layout/BottomNav';
import { cn } from '@/lib/utils';

const inter = Inter({ subsets: ['latin'] });

export const metadata: Metadata = {
  title: 'Workout Tracker',
  description: 'Premium Mobile-First Workout Tracker',
  viewport: 'width=device-width, initial-scale=1, maximum-scale=1, user-scalable=0',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={cn(inter.className, "bg-background text-foreground antialiased overflow-x-hidden")}>
        <main className="min-h-screen pb-20 max-w-md mx-auto bg-background shadow-2xl shadow-black relative overflow-hidden">
          {children}
        </main>
        <BottomNav />
      </body>
    </html>
  );
}
