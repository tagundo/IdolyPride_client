import game.qualiarts.idolypride.diagnostics.TrafficSampler;

/** Pure Java counter contract; contains no Android or network access. */
public final class TrafficSamplerTest {
    private static void check(boolean value, String message) {
        if (!value) throw new AssertionError(message);
    }

    private static final class Counters implements TrafficSampler.Counters {
        long time = 1000;
        long rx = 700;
        long tx = 300;
        int reads;
        public long elapsedRealtime() { return time; }
        public long rxBytes() { reads++; return rx; }
        public long txBytes() { reads++; return tx; }
    }

    public static void main(String[] args) {
        Counters counters = new Counters();
        TrafficSampler sampler = new TrafficSampler(counters);
        check(counters.reads == 2 && sampler.poll() == null, "baseline emits no fake initial progress");
        counters.time = 5999;
        check(sampler.poll() == null && counters.reads == 2, "no traffic reads before five seconds");
        counters.time = 6000; counters.rx = 1000; counters.tx = 400;
        TrafficSampler.Sample sample = sampler.poll();
        check(!sample.unavailable && sample.rxBytes == 300 && sample.txBytes == 100 && sample.elapsedMs == 5000,
                "first sample subtracts collector baseline");
        check(sampler.poll() == null && counters.reads == 4, "same timestamp does not sample twice");
        counters.time = 11000; counters.rx = 1500; counters.tx = 900;
        sample = sampler.poll();
        check(sample.rxBytes == 800 && sample.txBytes == 600 && sample.elapsedMs == 10000,
                "subsequent totals remain cumulative since collector start");
        counters.time = 16000; counters.rx = 1600; counters.tx = 900;
        sample = sampler.poll();
        check(sample.rxBytes == 900 && sample.txBytes == 600, "unchanged direction remains valid");
        counters.time = 21000; counters.rx = -1;
        check(sampler.poll().unavailable && sampler.poll() == null, "unsupported later counter reports once");

        counters = new Counters(); counters.tx = -1;
        sampler = new TrafficSampler(counters);
        check(sampler.poll().unavailable && sampler.poll() == null, "unsupported baseline reports once without zero totals");
        counters = new Counters(); sampler = new TrafficSampler(counters);
        counters.time = 6000; counters.rx = 699;
        check(sampler.poll().unavailable && sampler.poll() == null, "counter reset never fabricates negative or cumulative totals");
        counters = new Counters(); sampler = new TrafficSampler(counters); counters.time = 999;
        check(sampler.poll().unavailable, "monotonic clock reset is unavailable");
        counters = new Counters(); counters.rx = 0; counters.tx = 0; sampler = new TrafficSampler(counters);
        counters.time = 6000; counters.rx = Long.MAX_VALUE; counters.tx = Long.MAX_VALUE;
        sample = sampler.poll();
        check(sample.rxBytes == Long.MAX_VALUE && sample.txBytes == Long.MAX_VALUE, "signed long nonnegative byte bounds");
        System.out.println("TrafficSamplerTest passed");
    }
}
