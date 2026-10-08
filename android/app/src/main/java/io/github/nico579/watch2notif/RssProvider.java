package io.github.nico579.watch2notif;

import android.util.Xml;
import org.xmlpull.v1.XmlPullParser;
import java.io.ByteArrayInputStream;
import java.util.ArrayList;
import java.util.List;
import static io.github.nico579.watch2notif.Models.*;
import static io.github.nico579.watch2notif.ProviderSupport.*;

final class RssProvider implements Provider {
    private static final Metadata METADATA = new Metadata("rss", R.string.rss_label, R.string.rss_hint, 60);
    @Override public Metadata metadata() { return METADATA; }
    @Override public void validateSource(String source) {
        if (!webLink(source)) throw new IllegalArgumentException("rss");
    }
    @Override public List<Entry> fetch(Feed feed, Request request) throws SourceException {
        return parse(request.transport.request(feed.url, "", null, false), feed.url);
    }

    static List<Entry> parse(byte[] document, String sourceUrl) throws SourceException {
        try {
            XmlPullParser parser = Xml.newPullParser();
            parser.setFeature(XmlPullParser.FEATURE_PROCESS_NAMESPACES, true);
            parser.setFeature(XmlPullParser.FEATURE_PROCESS_DOCDECL, false);
            parser.setInput(new ByteArrayInputStream(document), null);
            List<Entry> entries = new ArrayList<>();
            int itemDepth = -1, fieldDepth = -1, authorDepth = -1;
            String field = "", id = "", title = "", author = "", link = "", summary = "", date = "", updated = "";
            StringBuilder text = new StringBuilder();
            List<String> bases = new ArrayList<>(); bases.add(sourceUrl);
            boolean recognized = false, rootClosed = false;
            int event;
            while ((event = parser.nextToken()) != XmlPullParser.END_DOCUMENT) {
                if (event == XmlPullParser.DOCDECL) throw new SourceException("parse");
                if (event == XmlPullParser.START_TAG) {
                    int depth = parser.getDepth();
                    String name = parser.getName(), ns = parser.getNamespace();
                    String parentBase = bases.get(bases.size() - 1);
                    String declaredBase = parser.getAttributeValue("http://www.w3.org/XML/1998/namespace", "base");
                    bases.add(declaredBase == null ? parentBase : resolve(parentBase, declaredBase));
                    if (depth == 1) recognized = "rss".equalsIgnoreCase(name) || "feed".equals(name) || "RDF".equals(name);
                    boolean contentNamespace = ns == null || ns.isEmpty() || ns.equals("http://www.w3.org/2005/Atom")
                            || ns.equals("http://purl.org/rss/1.0/");
                    if (contentNamespace && itemDepth < 0 && ("item".equals(name) || "entry".equals(name))) {
                        itemDepth = depth; id = title = author = link = summary = date = updated = "";
                        String about = parser.getAttributeValue("http://www.w3.org/1999/02/22-rdf-syntax-ns#", "about");
                        if (about != null) id = resolve(bases.get(bases.size() - 1), about);
                    } else if (itemDepth > 0) {
                        if (depth == itemDepth + 1 && "author".equals(name) && contentNamespace) authorDepth = depth;
                        if (fieldDepth < 0 && ((depth == itemDepth + 1 && (contentNamespace
                                || "http://purl.org/dc/elements/1.1/".equals(ns)
                                || "http://purl.org/rss/1.0/modules/content/".equals(ns)))
                                || (authorDepth > 0 && depth == authorDepth + 1 && "name".equals(name)))) {
                            if ("link".equals(name)) {
                                String href = parser.getAttributeValue(null, "href"), rel = parser.getAttributeValue(null, "rel");
                                if (href != null && (rel == null || "alternate".equals(rel))) link = resolve(bases.get(bases.size() - 1), href);
                            }
                            field = name; fieldDepth = depth; text.setLength(0);
                            // Atom author is a container; capture its name child instead.
                            if ("author".equals(name) && "http://www.w3.org/2005/Atom".equals(ns)) fieldDepth = -1;
                        }
                    }
                } else if ((event == XmlPullParser.TEXT || event == XmlPullParser.CDSECT || event == XmlPullParser.ENTITY_REF) && fieldDepth > 0) {
                    if (parser.getText() != null) text.append(parser.getText());
                } else if (event == XmlPullParser.END_TAG) {
                    int depth = parser.getDepth();
                    if (depth == 1) rootClosed = true;
                    if (fieldDepth == depth) {
                        String value = text.toString().trim();
                        switch (field) {
                            case "guid": case "id": if (!value.isEmpty()) id = value; break;
                            case "title": title = plain(value); break;
                            case "author": case "creator": case "name": author = plain(value); break;
                            case "link": if (!value.isEmpty()) link = resolve(bases.get(bases.size() - 1), value); break;
                            case "description": case "summary": summary = plain(value); break;
                            case "content": case "encoded": if (summary.isEmpty()) summary = plain(value); break;
                            case "pubDate": case "published": case "date": date = value; break;
                            case "updated": updated = value; break;
                            default: break;
                        }
                        fieldDepth = -1;
                    }
                    if (authorDepth == depth) authorDepth = -1;
                    if (itemDepth == depth) {
                        long created = timestamp(date); if (created == 0) created = timestamp(updated);
                        entries.add(new Entry(id, title, author, link, summary, created)); itemDepth = -1;
                        if (entries.size() > 2000) throw new SourceException("parse");
                    }
                    if (bases.size() > 1) bases.remove(bases.size() - 1);
                }
            }
            if (!recognized || !rootClosed || itemDepth >= 0) throw new SourceException("parse");
            return entries;
        } catch (SourceException failure) { throw failure; }
        catch (Exception ignored) { throw new SourceException("parse"); }
    }
}
