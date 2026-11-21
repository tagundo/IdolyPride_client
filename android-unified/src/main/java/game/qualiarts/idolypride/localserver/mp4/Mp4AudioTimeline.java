package game.qualiarts.idolypride.localserver.mp4;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;

/** Finalizes exact video sample clocks and the AAC presentation interval in our private MP4. */
public final class Mp4AudioTimeline {
    private static final int MAX_MOOV_BYTES = 16 * 1024 * 1024;
    private static final long U32 = 0xffffffffL;
    private Mp4AudioTimeline() {}

    /**
     * The caller has closed MediaMuxer and verified the actual encoder delay.
     * This supports unfragmented, zero-origin video and one AAC-LC audio track.
     * All validation and reconstruction precedes the first write. A trailing
     * moov is replaced; a fast-start moov is retired as free space after its
     * replacement is appended. Every media chunk's absolute offset is retained.
     */
    public static void finalizeFile(File mp4, int sampleRate, long logicalPcmFrames,
            int encoderDelayFrames, long encodedAacPackets) throws IOException {
        finalizeFile(mp4, sampleRate, logicalPcmFrames, encoderDelayFrames, encodedAacPackets, null);
    }

    /** The producer has already verified every encoded frame's index and exact input PTS. */
    public static void finalizeFile(File mp4, int sampleRate, long logicalPcmFrames,
            int encoderDelayFrames, long encodedAacPackets, int fpsNumerator,
            int fpsDenominator, long videoFrames) throws IOException {
        require(fpsNumerator > 0 && fpsNumerator <= 1_000_000 && fpsDenominator > 0
                && fpsDenominator <= 10_000 && videoFrames > 0 && videoFrames <= U32,
                "Invalid verified video clock");
        int common = (int)gcd(fpsNumerator, fpsDenominator);
        finalizeFile(mp4, sampleRate, logicalPcmFrames, encoderDelayFrames, encodedAacPackets,
                new VideoClock(fpsNumerator / common, fpsDenominator / common, videoFrames));
    }

    private static final class VideoClock {
        final int numerator, denominator; final long frames;
        VideoClock(int numerator, int denominator, long frames) {
            this.numerator = numerator; this.denominator = denominator; this.frames = frames;
        }
    }

    private static void finalizeFile(File mp4, int sampleRate, long logicalPcmFrames,
            int encoderDelayFrames, long encodedAacPackets, VideoClock video) throws IOException {
        require(sampleRate > 0 && logicalPcmFrames > 0 && encoderDelayFrames >= 0
                && encodedAacPackets > 0, "Invalid AAC timing contract");
        require(mp4 != null && mp4.isFile(), "Missing MP4 file");
        long rawFrames = multiply(encodedAacPackets, 1024);
        require(encoderDelayFrames <= rawFrames
                && logicalPcmFrames <= rawFrames - encoderDelayFrames,
                "AAC packets do not contain the complete logical PCM interval");
        try (RandomAccessFile file = new RandomAccessFile(mp4, "rw")) {
            long length = file.length(), offset = 0, movieOffset = -1;
            byte[] movie = null;
            boolean media = false;
            while (offset < length) {
                require(length - offset >= 8, "Truncated top-level box");
                file.seek(offset);
                long size = Integer.toUnsignedLong(file.readInt());
                byte[] typeBytes = new byte[4]; file.readFully(typeBytes);
                String type = new String(typeBytes, StandardCharsets.ISO_8859_1);
                int header = 8;
                if (size == 1) { require(length - offset >= 16, "Truncated large box");
                    size = file.readLong(); header = 16; }
                if (size == 0) size = length - offset;
                require(size >= header && size <= length - offset, "Invalid top-level box size");
                require(!"moof".equals(type) && !"sidx".equals(type), "Fragmented MP4 is unsupported");
                if ("mdat".equals(type)) media = true;
                if ("moov".equals(type)) {
                    require(movie == null, "Expected exactly one movie metadata box");
                    require(size <= MAX_MOOV_BYTES, "Movie metadata exceeds the limit");
                    movieOffset = offset; movie = new byte[(int)size];
                    file.seek(offset); file.readFully(movie);
                }
                offset += size;
            }
            require(movie != null && media, "Missing movie metadata or media data");
            byte[] rebuilt = rebuild(movie, sampleRate, logicalPcmFrames,
                    encoderDelayFrames, encodedAacPackets, rawFrames, video);
            require(rebuilt.length <= MAX_MOOV_BYTES, "Rebuilt movie metadata exceeds the limit");
            require(file.length() == length, "MP4 changed during finalization");
            if (movieOffset + movie.length == length) {
                file.seek(movieOffset); file.write(rebuilt);
                file.setLength(movieOffset + rebuilt.length); file.getFD().sync();
            } else {
                // MediaMuxer may reserve front metadata space for short movies.
                // Append and sync its replacement first, then retire only the
                // old box's type. No absolute sample/chunk offset is rebased.
                require(length <= Long.MAX_VALUE - rebuilt.length, "MP4 length overflow");
                file.seek(length); file.write(rebuilt); file.getFD().sync();
                file.seek(movieOffset + 4); file.write(new byte[] {'f','r','e','e'});
                file.getFD().sync();
            }
        }
    }

    private static byte[] rebuild(byte[] data, int rate, long frames, int delay,
            long packets, long rawFrames, VideoClock video) throws IOException {
        Box root = boxes(data, 0, data.length).get(0);
        List<Box> children = boxes(data, root.payload, root.end);
        require(root.end == data.length && "moov".equals(root.type), "Invalid moov");
        require(find(children, "mvex", false) == null, "Fragmented movie is unsupported");
        Box movieHeader = find(children, "mvhd", true);
        long oldScale = timescale(data, movieHeader), newScale = multiply(oldScale / gcd(oldScale, rate), rate);
        if (video != null) newScale = multiply(newScale / gcd(newScale, video.numerator), video.numerator);
        require(oldScale > 0 && newScale <= U32, "Movie timescale cannot represent exact PCM samples");
        long factor = newScale / oldScale, audioDuration = multiply(frames, newScale / rate);
        int audioTracks = 0, videoTracks = 0;
        long movieDuration = 0;
        List<byte[]> result = new ArrayList<>();
        for (Box child : children) {
            if (!"trak".equals(child.type)) { result.add(copy(data, child)); continue; }
            List<Box> track = boxes(data, child.payload, child.end);
            require(find(track, "edts", false) == null, "Preexisting track edits are unsupported");
            Box trackHeader = find(track, "tkhd", true), mdia = find(track, "mdia", true);
            List<Box> media = boxes(data, mdia.payload, mdia.end);
            Box handler = find(media, "hdlr", true);
            require(handler.end - handler.payload >= 24, "Truncated media handler");
            String kind = type(data, handler.payload + 8);
            boolean audio = "soun".equals(kind);
            require(audio || "vide".equals(kind), "Unsupported track handler");
            long duration;
            if (audio) { audioTracks++; validateAudio(data, media, rate, packets, rawFrames); duration = audioDuration; }
            else { videoTracks++; duration = video == null ? multiply(duration(data, trackHeader), factor)
                    : multiply(multiply(video.frames, video.denominator), newScale / video.numerator); }
            movieDuration = Math.max(movieDuration, duration);
            List<byte[]> updated = new ArrayList<>();
            for (Box part : track) {
                updated.add(part == trackHeader ? updateHeader(data, part, duration, -1)
                        : !audio && video != null && part == mdia ? rebuildVideo(data, mdia, video) : copy(data, part));
                if (audio && part == trackHeader) updated.add(edit(audioDuration, delay));
            }
            result.add(box("trak", join(updated)));
        }
        require(audioTracks == 1 && videoTracks >= 1 && (video == null || videoTracks == 1),
                "Expected one AAC track and one verified video track");
        for (int i = 0; i < children.size(); i++) if (children.get(i) == movieHeader)
            result.set(i, updateHeader(data, movieHeader, movieDuration, newScale));
        return box("moov", join(result));
    }

    private static byte[] rebuildVideo(byte[] data, Box mdia, VideoClock clock) throws IOException {
        List<Box> media = boxes(data, mdia.payload, mdia.end);
        Box header = find(media, "mdhd", true), minf = find(media, "minf", true);
        List<Box> information = boxes(data, minf.payload, minf.end);
        Box stbl = find(information, "stbl", true);
        List<Box> table = boxes(data, stbl.payload, stbl.end);
        require(find(table, "ctts", false) == null, "Reordered video samples are unsupported");
        Box stts = find(table, "stts", true), stsz = find(table, "stsz", true), stsd = find(table, "stsd", true);
        fullV0(data, stts); require(stts.end - stts.payload >= 8, "Truncated video timing");
        long entries = u32(data, stts.payload + 4), count = 0;
        require(entries <= (stts.end - stts.payload - 8) / 8
                && entries * 8 == stts.end - stts.payload - 8, "Invalid video timing table");
        for (int p = stts.payload + 8; p < stts.end; p += 8) {
            long samples = u32(data, p);
            require(samples > 0 && u32(data, p + 4) > 0 && samples <= clock.frames - count,
                    "Invalid verified video sample count or duration"); count += samples;
        }
        require(count == clock.frames, "Video frame count differs from timing table");
        fullV0(data, stsz); require(stsz.end - stsz.payload >= 12, "Truncated video sample sizes");
        require(u32(data, stsz.payload + 8) == clock.frames, "Video frame count differs from size table");
        long fixed = u32(data, stsz.payload + 4);
        require(stsz.end - stsz.payload == 12 + (fixed == 0 ? multiply(clock.frames, 4) : 0), "Invalid video sample sizes");
        if (fixed == 0) for (int p = stsz.payload + 12; p < stsz.end; p += 4)
            require(u32(data, p) > 0, "Empty encoded video sample");
        fullV0(data, stsd); require(stsd.end - stsd.payload >= 8 && u32(data, stsd.payload + 4) == 1,
                "Expected one video sample description");
        List<Box> descriptions = boxes(data, stsd.payload + 8, stsd.end);
        require(descriptions.size() == 1 && descriptions.get(0).end - descriptions.get(0).payload >= 78
                && ("avc1".equals(descriptions.get(0).type) || "hvc1".equals(descriptions.get(0).type)
                    || "hev1".equals(descriptions.get(0).type)), "Unsupported video sample description");
        long mediaDuration = multiply(clock.frames, clock.denominator);
        long expectedOldTicks = multiply(mediaDuration, timescale(data, header)) / clock.numerator;
        long oldDuration = duration(data, header);
        require(oldDuration >= expectedOldTicks && oldDuration - expectedOldTicks <= 1,
                "Video media duration differs from the verified clock");
        byte[] timing = new byte[16]; put32(timing, 4, 1);
        put32(timing, 8, clock.frames); put32(timing, 12, clock.denominator);
        List<byte[]> samples = new ArrayList<>();
        for (Box item : table) samples.add(item == stts ? box("stts", timing) : copy(data, item));
        List<byte[]> infos = new ArrayList<>();
        for (Box item : information) infos.add(item == stbl ? box("stbl", join(samples)) : copy(data, item));
        List<byte[]> output = new ArrayList<>();
        for (Box item : media) output.add(item == header ? updateHeader(data, header, mediaDuration, clock.numerator)
                : item == minf ? box("minf", join(infos)) : copy(data, item));
        return box("mdia", join(output));
    }

    private static void validateAudio(byte[] data, List<Box> media, int rate,
            long packets, long rawFrames) throws IOException {
        Box header = find(media, "mdhd", true);
        require(timescale(data, header) == rate && duration(data, header) == rawFrames,
                "AAC media clock does not match encoded samples");
        Box minf = find(media, "minf", true);
        Box stbl = find(boxes(data, minf.payload, minf.end), "stbl", true);
        List<Box> table = boxes(data, stbl.payload, stbl.end);
        Box stts = find(table, "stts", true), stsz = find(table, "stsz", true), stsd = find(table, "stsd", true);
        fullV0(data, stts); require(stts.end - stts.payload >= 8, "Truncated sample timing");
        long entries = u32(data, stts.payload + 4), total = 0;
        require(entries <= (stts.end - stts.payload - 8) / 8
                && entries * 8 == stts.end - stts.payload - 8, "Invalid sample timing table");
        for (int p = stts.payload + 8; p < stts.end; p += 8) {
            long count = u32(data, p);
            require(count > 0 && u32(data, p + 4) == 1024, "AAC packets must contain 1024 samples");
            require(count <= Long.MAX_VALUE - total, "Sample count overflow"); total += count;
        }
        require(total == packets, "AAC packet count differs from timing table");
        fullV0(data, stsz); require(stsz.end - stsz.payload >= 12, "Truncated sample sizes");
        require(u32(data, stsz.payload + 8) == packets, "AAC sample size count differs");
        long fixed = u32(data, stsz.payload + 4);
        require(stsz.end - stsz.payload == 12 + (fixed == 0 ? multiply(packets, 4) : 0), "Invalid sample sizes");
        if (fixed == 0) for (int p = stsz.payload + 12; p < stsz.end; p += 4)
            require(u32(data, p) > 0, "Empty AAC packet");
        fullV0(data, stsd); require(stsd.end - stsd.payload >= 8 && u32(data, stsd.payload + 4) == 1,
                "Expected one AAC sample description");
        List<Box> descriptions = boxes(data, stsd.payload + 8, stsd.end);
        require(descriptions.size() == 1, "Invalid AAC sample description count");
        Box sample = descriptions.get(0);
        require("mp4a".equals(sample.type) && sample.end - sample.payload >= 28,
                "Expected an mp4a sample entry");
        int channels = u16(data, sample.payload + 16);
        require(u16(data, sample.payload + 8) == 0 && (channels == 1 || channels == 2)
                && u16(data, sample.payload + 18) == 16 && u32(data, sample.payload + 24) == (long)rate * 65536,
                "Unsupported AAC sample entry format");
        Box esds = find(boxes(data, sample.payload + 28, sample.end), "esds", true);
        fullV0(data, esds); validateEsds(data, esds.payload + 4, esds.end, rate, channels);
    }

    private static void validateEsds(byte[] data, int start, int end, int rate, int channels) throws IOException {
        int[] cursor = { start }; int esEnd = descriptor(data, cursor, end, 3);
        require(esEnd - cursor[0] >= 3, "Truncated ES descriptor");
        int flags = data[cursor[0] + 2] & 255; cursor[0] += 3;
        if ((flags & 128) != 0) cursor[0] += 2;
        if ((flags & 64) != 0) { require(cursor[0] < esEnd, "Truncated ES URL"); cursor[0] += 1 + (data[cursor[0]] & 255); }
        if ((flags & 32) != 0) cursor[0] += 2;
        int decoderEnd = descriptor(data, cursor, esEnd, 4);
        require(decoderEnd - cursor[0] >= 13 && (data[cursor[0]] & 255) == 0x40
                && ((data[cursor[0] + 1] & 255) >>> 2) == 5, "Expected MPEG-4 audio decoder");
        cursor[0] += 13; int ascEnd = descriptor(data, cursor, decoderEnd, 5);
        int[] bit = { cursor[0] * 8 };
        require(bits(data, bit, ascEnd, 5) == 2, "Only AAC-LC is supported");
        int index = bits(data, bit, ascEnd, 4);
        int[] rates = {96000,88200,64000,48000,44100,32000,24000,22050,16000,12000,11025,8000,7350};
        int actualRate = index == 15 ? bits(data, bit, ascEnd, 24) : index < rates.length ? rates[index] : 0;
        require(actualRate == rate && bits(data, bit, ascEnd, 4) == channels
                && bits(data, bit, ascEnd, 1) == 0 && bits(data, bit, ascEnd, 1) == 0
                && bits(data, bit, ascEnd, 1) == 0, "AAC configuration differs from PCM");
    }
    private static int descriptor(byte[] data, int[] cursor, int end, int tag) throws IOException {
        require(cursor[0] >= 0 && cursor[0] < end && (data[cursor[0]++] & 255) == tag, "Unexpected MPEG-4 descriptor");
        int length = 0, value = 128, count = 0;
        while ((value & 128) != 0 && count++ < 4) { require(cursor[0] < end, "Truncated descriptor length");
            value = data[cursor[0]++] & 255; length = (length << 7) | (value & 127); }
        require((value & 128) == 0 && length <= end - cursor[0], "Invalid descriptor length");
        return cursor[0] + length;
    }
    private static int bits(byte[] data, int[] cursor, int end, int count) throws IOException {
        require((long)cursor[0] + count <= (long)end * 8, "Truncated AAC configuration");
        int value = 0; while (count-- > 0) { int p = cursor[0]++; value = (value << 1) | ((data[p / 8] >> (7 - p % 8)) & 1); }
        return value;
    }

    private static byte[] edit(long duration, int delay) throws IOException {
        byte[] payload = new byte[28]; payload[0] = 1; put32(payload, 4, 1);
        put64(payload, 8, duration); put64(payload, 16, delay); put32(payload, 24, 0x10000);
        return box("edts", box("elst", payload));
    }
    private static long timescale(byte[] data, Box header) throws IOException {
        int version = headerVersion(data, header); long scale = u32(data, header.payload + (version == 0 ? 12 : 20));
        require(scale > 0, "Zero media timescale"); return scale;
    }
    private static long duration(byte[] data, Box header) throws IOException {
        int version = headerVersion(data, header), at = header.payload
                + ("tkhd".equals(header.type) ? version == 0 ? 20 : 28 : version == 0 ? 16 : 24);
        return version == 0 ? u32(data, at) : u64(data, at);
    }
    private static int headerVersion(byte[] data, Box header) throws IOException {
        require(header.end - header.payload >= 4, "Truncated timing header"); int version = data[header.payload] & 255;
        int minimum = "tkhd".equals(header.type) ? version == 0 ? 84 : 96
                : "mvhd".equals(header.type) ? version == 0 ? 100 : 112 : version == 0 ? 24 : 36;
        require(version <= 1 && header.end - header.payload >= minimum, "Unsupported timing header"); return version;
    }
    private static byte[] updateHeader(byte[] data, Box header, long duration, long scale) throws IOException {
        int version = headerVersion(data, header);
        require(duration >= 0 && (version == 1 || duration <= U32), "Timing header duration overflows its version");
        byte[] value = copy(data, header); int base = header.payload - header.start;
        int at = base + ("tkhd".equals(header.type) ? version == 0 ? 20 : 28 : version == 0 ? 16 : 24);
        if (version == 0) put32(value, at, duration); else put64(value, at, duration);
        if (scale >= 0) put32(value, base + (version == 0 ? 12 : 20), scale);
        return value;
    }
    private static final class Box {
        final int start, payload, end; final String type;
        Box(int start, int payload, int end, String type) { this.start=start; this.payload=payload; this.end=end; this.type=type; }
    }
    private static List<Box> boxes(byte[] data, int start, int end) throws IOException {
        List<Box> result = new ArrayList<>(); require(start >= 0 && start <= end && end <= data.length, "Invalid child range");
        while (start < end) { require(end - start >= 8, "Truncated box"); long size = u32(data, start); int header = 8;
            if (size == 1) { require(end-start >= 16, "Truncated large box"); size=u64(data,start+8); header=16; }
            require(size >= header && size <= end-start, "Invalid child box size");
            require(result.size()<4096,"Too many child boxes");
            result.add(new Box(start,start+header,start+(int)size,type(data,start+4))); start+=(int)size; }
        return result;
    }
    private static Box find(List<Box> list, String type, boolean required) throws IOException {
        Box result=null; for (Box item:list) if (type.equals(item.type)) { require(result==null,"Duplicate "+type); result=item; }
        require(!required || result!=null,"Missing "+type); return result;
    }
    private static void fullV0(byte[] data, Box box) throws IOException {
        require(box.end-box.payload >= 4 && u32(data,box.payload)==0,"Unsupported full box "+box.type);
    }
    private static byte[] copy(byte[] data, Box box) { byte[] value=new byte[box.end-box.start]; System.arraycopy(data,box.start,value,0,value.length); return value; }
    private static byte[] join(List<byte[]> pieces) throws IOException {
        long length=0; for(byte[] value:pieces) length+=value.length; require(length<=MAX_MOOV_BYTES,"Metadata exceeds limit");
        ByteArrayOutputStream out=new ByteArrayOutputStream((int)length); for(byte[] value:pieces) out.write(value,0,value.length); return out.toByteArray();
    }
    private static byte[] box(String type, byte[] payload) throws IOException {
        require(payload.length<=MAX_MOOV_BYTES-8,"Box exceeds limit"); byte[] value=new byte[payload.length+8]; put32(value,0,value.length);
        byte[] name=type.getBytes(StandardCharsets.ISO_8859_1); System.arraycopy(name,0,value,4,4); System.arraycopy(payload,0,value,8,payload.length); return value;
    }
    private static String type(byte[] data,int at) throws IOException { require(at>=0&&data.length-at>=4,"Truncated type"); return new String(data,at,4,StandardCharsets.ISO_8859_1); }
    private static int u16(byte[] data,int at) throws IOException { require(at>=0&&data.length-at>=2,"Truncated uint16"); return ((data[at]&255)<<8)|(data[at+1]&255); }
    private static long u32(byte[] data,int at) throws IOException { require(at>=0&&data.length-at>=4,"Truncated uint32"); return ((long)(data[at]&255)<<24)|((long)(data[at+1]&255)<<16)|((long)(data[at+2]&255)<<8)|(data[at+3]&255); }
    private static long u64(byte[] data,int at) throws IOException { long high=u32(data,at); require(high<=0x7fffffffL,"Unsigned duration exceeds signed range"); return (high<<32)|u32(data,at+4); }
    private static void put32(byte[] data,int at,long value) { data[at]=(byte)(value>>>24); data[at+1]=(byte)(value>>>16); data[at+2]=(byte)(value>>>8); data[at+3]=(byte)value; }
    private static void put64(byte[] data,int at,long value) { put32(data,at,value>>>32); put32(data,at+4,value); }
    private static long gcd(long a,long b) { while(b!=0){long next=a%b;a=b;b=next;}return a; }
    private static long multiply(long a,long b) throws IOException { require(a>=0&&b>=0&&(a==0||b<=Long.MAX_VALUE/a),"Timing multiplication overflow");return a*b; }
    private static void require(boolean value,String message) throws IOException { if(!value)throw new IOException(message); }
}
