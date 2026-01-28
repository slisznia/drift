# Effective Drift

Common idioms for programs that won’t ghost you in prod.

## Shared state + callbacks (Arc + Mutex)

When you need multiple handlers that all mutate the same receiver object, put
the receiver in an `Arc` and wrap it in a `Mutex`. Each handler captures a
clone, takes the lock, and mutates through a guard. This avoids ownership
conflicts and keeps the emitter dumb.

```drift
import std.core as core;
import std.concurrency as conc;

struct StateMachine { state: Int }

implement StateMachine {
    fn on_signal_x(self: &mut Self, e: &Event) -> Void { self.state = self.state + 1; }
    fn on_signal_y(self: &mut Self, e: &Event) -> Void { self.state = self.state - 1; }
    fn on_signal_z(self: &mut Self, e: &Event) -> Void { self.state = 0; }
}

fn register_handlers(bus: &mut EventBus) -> Void {
    var sm: conc.Arc<conc.Mutex<StateMachine>> = conc.arc(conc.mutex(StateMachine(state = 0)));
    var sm_x: conc.Arc<conc.Mutex<StateMachine>> = sm.clone();
    var cb_x: core.Callback1<&Event, Void> = core.callback1(|e: &Event| captures(move sm_x) => {
        var guard = conc.lock(sm_x);
        guard.get_mut().on_signal_x(e);
        return;
    });
    bus.on_x(move cb_x);
    var sm_y: conc.Arc<conc.Mutex<StateMachine>> = sm.clone();
    var cb_y: core.Callback1<&Event, Void> = core.callback1(|e: &Event| captures(move sm_y) => {
        var guard = conc.lock(sm_y);
        guard.get_mut().on_signal_y(e);
        return;
    });
    bus.on_y(move cb_y);
    var sm_z: conc.Arc<conc.Mutex<StateMachine>> = sm.clone();
    var cb_z: core.Callback1<&Event, Void> = core.callback1(|e: &Event| captures(move sm_z) => {
        var guard = conc.lock(sm_z);
        guard.get_mut().on_signal_z(e);
        return;
    });
    bus.on_z(move cb_z);
}
```

Notes

- This works with owned callbacks and does not rely on borrowed captures.

## Iterate, then mutate

Many container iterators are invalidated by mutation. When you need to delete or
update entries while scanning, collect keys first and apply changes afterward.

```drift
fn prune(map: &mut HashMap<String, Int>) -> Void {
    var dead = Array<String>::new();
    for (k, v) in map.iter() {
        if *v == 0 { dead.push(k.clone()); }
    }
    for k in dead.iter() {
        map.remove(k);
    }
}
```

This keeps iterator invalidation out of your way and makes the intent obvious.

## Keep borrows small and explicit

When a function gets complex, it helps to shrink the lifetime of borrows by
using local scopes. This avoids accidental conflicts and reads clearly.

```drift
fn update_user(db: &mut Db, id: Int, patch: Patch) -> Bool {
    {
        val u = db.get_mut(id);
        if u.is_none() { return false; }
        u.unwrap().apply(patch);
    }
    db.mark_dirty(id);
    true
}
```

The inner block makes it obvious when the borrow ends.

## Prefer structs for product data; use variants to tag meaning

If a type is just “some fields grouped together,” use a `struct`. If you want a
named constructor, pattern-matching boundary, or future extensibility, use a
`variant` (even with a single arm).

```drift
struct Point { x: Int, y: Int }
// Construct: Point(x = 2, y = 3)

variant UserId {
    UserId(Int),
}
// Construct: UserId(42); match on UserId(...)
```

Single-arm variants are useful for semantic tagging (“this Int is a UserId”),
and they keep the door open to add more cases later without changing the type’s
name or its call sites.

## Prefer “own the data” for long-lived callbacks

If a callback will live longer than the scope it was created in, capture owned
data (or an `Arc`) instead of borrowing. This keeps lifetimes simple and avoids
surprises later.

```drift
fn install(bus: &mut EventBus, cfg: Config) -> Void {
    var cfg = conc.arc(cfg);
    var cfg2 = cfg.clone();
    bus.on_tick(core.callback0(|| => {
        cfg2.refresh();
    }));
}
```

It’s slightly more verbose up front, but it scales well as the program grows.
