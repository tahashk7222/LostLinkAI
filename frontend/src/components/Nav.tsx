"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { api } from "@/lib/api";

export function Nav() {
  const { user, logout } = useAuth();
  const pathname = usePathname();
  const [unread, setUnread] = useState(0);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!user) return;
    let alive = true;
    const load = () =>
      api<{ unread: number }>("/notifications?unread_only=true&limit=1")
        .then((r) => alive && setUnread(r.unread))
        .catch(() => {});
    load();
    const t = setInterval(load, 20000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, [user, pathname]);

  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  const links = user
    ? [
        ["/dashboard", "Dashboard"],
        ["/reports", "Browse"],
        ["/matches", "Matches"],
        ["/cases", "Cases"],
        ...(user.role === "ADMIN" ? [["/admin", "Admin"]] : []),
      ]
    : [];

  return (
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
        <Link href={user ? "/dashboard" : "/"} className="flex items-center gap-2 text-lg font-bold text-slate-900">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-brand-600 text-sm text-white">LL</span>
          LostLink <span className="text-brand-600">AI</span>
        </Link>
        <button className="btn-secondary sm:hidden" onClick={() => setOpen(!open)} aria-label="Menu">
          ☰
        </button>
        <nav className={`${open ? "flex" : "hidden"} absolute left-0 right-0 top-full flex-col gap-1 border-b border-slate-200 bg-white p-3 sm:static sm:flex sm:flex-row sm:items-center sm:border-0 sm:p-0`}>
          {links.map(([href, label]) => (
            <Link
              key={href}
              href={href}
              className={`rounded-lg px-3 py-2 text-sm ${pathname.startsWith(href) ? "bg-brand-50 font-medium text-brand-700" : "text-slate-600 hover:bg-slate-100"}`}
            >
              {label}
            </Link>
          ))}
          {user ? (
            <>
              <Link href="/notifications" className="relative rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-100">
                Notifications
                {unread > 0 && (
                  <span className="ml-1 rounded-full bg-rose-600 px-1.5 py-0.5 text-xs font-semibold text-white">{unread}</span>
                )}
              </Link>
              <Link href="/profile" className="rounded-lg px-3 py-2 text-sm text-slate-600 hover:bg-slate-100">
                {user.name.split(" ")[0]}
              </Link>
              <button onClick={logout} className="rounded-lg px-3 py-2 text-left text-sm text-slate-500 hover:bg-slate-100">
                Log out
              </button>
            </>
          ) : (
            <>
              <Link href="/login" className="btn-secondary">Log in</Link>
              <Link href="/register" className="btn-primary">Sign up</Link>
            </>
          )}
        </nav>
      </div>
    </header>
  );
}
