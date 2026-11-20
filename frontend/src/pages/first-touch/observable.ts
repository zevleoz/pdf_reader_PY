/** Observe only data containers: native browser instances must retain their receiver. */
export function observable<T extends object>(value: T, notify: () => void, active: () => boolean = () => true): T {
  const proxies = new WeakSet<object>();
  const cache = new WeakMap<object, object>();
  function wrap<V>(item: V): V {
    if (!item || typeof item !== 'object') return item;
    if (proxies.has(item)) return item;
    const proto = Object.getPrototypeOf(item);
    if (proto !== Object.prototype && proto !== Array.prototype && proto !== null) return item;
    const cached = cache.get(item);
    if (cached) return cached as V;
    const proxy = new Proxy(item, {
      get(target, key, receiver) { return wrap(Reflect.get(target, key, receiver)); },
      set(target, key, next) {
        if (!active()) return true;
        const previous = Reflect.get(target, key);
        const ok = Reflect.set(target, key, next);
        if (ok && previous !== next) notify();
        return ok;
      },
      deleteProperty(target, key) {
        if (!active()) return true;
        const ok = Reflect.deleteProperty(target, key);
        if (ok) notify();
        return ok;
      },
    });
    cache.set(item, proxy);
    proxies.add(proxy);
    return proxy as V;
  }
  return wrap(value);
}
