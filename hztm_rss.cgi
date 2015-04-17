#!/usr/bin/perl
# Matija Nalis <mnalis-git@voyager.hr> GPLv3+, started 2015-04-17
#
# detektira zalihe krvi u HZTMu, kako bi RSSom mogao dojaviti korisnicima kada neke krvne grupe nedostaje.
#

# FIXME: Wide character in print at ./hztm_rss.cgi line 97.

use strict;
use warnings;
use Carp qw(verbose);
use autodie;
use feature qw(say);


use CGI;
use Encode qw(decode);
use HTML::TreeBuilder::XPath;
use XML::Feed;



my $q = new CGI;
my $xml_feed = 'Atom';	# 'Atom' or 'RSS' -- FIXME choose by cgi->param
my $HZTM_URL = 'http://hztm.hr/hr/content/22/zalihe-krvi/831/zalihe-krvi';

######################
#### generate RSS ####
######################

my $mime = ('Atom' eq $xml_feed) ? 'application/atom+xml' : 'application/rss+xml';
my $feed = XML::Feed->new($xml_feed);
my $TAG_BASE = 'tag:mnalis.com,2015-04-17:/hztm';
my $feed_id = '/HZTM-krv-unoff'; 
my $url = $q->url( -query => 1, -full => 1, -rewrite => 1);
$feed->self_link($url);
$feed->title( "Nedostatak krvih grupa u HZTM" );
$feed->id( "$TAG_BASE/$feed_id" );
$feed->description( 'Niske zalihe krvi - za dobrovoljne darivatelje krvi Hrvatskog zavoda za transfuzijsku medicinu' );
$feed->language('hr');
$feed->copyright('Informacije su preuzete iz vanjskih izvora te su podložne promjeni i ne odgovaramo za njihovu točnost');
$feed->author('mnalis-hztm@voyager.hr ( http://mnalis.com/hztm/ )');
$feed->generator('hztm_rss.cgi 2015-04-17 using XML::Feed ' . $XML::Feed::VERSION);
$feed->link($url);

my $last_timestamp = 0;
my $events_ref = [{ id => 1, opis => 'neki opis', grupa=>'A+', nedostaje => 1, datum => '2015-01-01', posto => 30, timestamp => time() }];
foreach my $event (@$events_ref) {	# FIXME
    my $entry = XML::Feed::Entry->new($xml_feed);
    $entry->id( "$TAG_BASE/" . $event->{id} . $feed_id );              # see http://taguri.org (RFC 4151), and http://web.archive.org/web/20110514113830/http://diveintomark.org/archives/2004/05/28/howto-atom-id
    $entry->link( $HZTM_URL );

    if ($event->{nedostaje}) {
        $entry->title( "$event->{datum} Nedostaje " );
        $entry->content( qq{Sa datumom $event->{datum} nedostaje krvne grupe $event->{grupa} (zalihe su samo $event->{posto}%)\nMolimo da se odazovete dobrovoljnom davanju krvi!\n\nHvala } );
    } else {
        $entry->title( "$event->{datum} Ponovno ima dovoljno krvne grupe $event->{grupa}" );
        $entry->content( qq{Sa datumom $event->{datum} ponovo ima dovoljno ($event->{posto}%) krvne grupe $event->{grupa} } );
    }
    
    # NB it could be confusing to readers when RSS reader shows dates (which are NOT dates of event!). 
    # But if we remove them, then RSS readers couldn't show updated events... So we'd need a kludge, 
    # like removing modified() so no date is shown, making modified(datum) and issued(updated_unix), and/or
    # changing entry->id. Leave it as it is for now... /mn/ 2013-11-11
    $entry->issued(   DateTime->from_epoch(epoch => $event->{timestamp}) );
    $entry->modified( DateTime->from_epoch(epoch => $event->{timestamp}) );
    
    $last_timestamp = $event->{timestamp} if $event->{timestamp} > $last_timestamp;	# increment last feed update timestamp if needed.
    
    $feed->add_entry($entry);
}
$feed->modified (DateTime->from_epoch(epoch => $last_timestamp));


########################
#### parse the HTML ####
########################


#my $HZTM_FILE = 'zalihe-krvi'; my $tree= HTML::TreeBuilder::XPath->new_from_file($HZTM_FILE);	# DEBUG ONLY
my $tree= HTML::TreeBuilder::XPath->new_from_url($HZTM_URL);

my @sve=$tree->findnodes( '/html/body//div[@id="supplies"]/div[contains(concat(" ", normalize-space(@class), " "),"measure")]' );

for my $jedna (@sve) {
  my $posto = int ($jedna->findnodes( 'div[@class="outer"]/div[@class="inner"]' )->[0]->attr('data-percent'));
  my $ime = $jedna->findnodes( 'div[contains(concat(" ", normalize-space(@class), " "),"name")]' )->[0];
  my $grupa = $ime->content->[0];
  my $attr = $ime->attr('class');
  my $nedostaje = ($attr =~ /\bbig\b/);
  #say "grupa=$grupa, attr=$attr, nedostaje=$nedostaje, posto=$posto";
  say '' . ($nedostaje?'Nedostaje':'Ima dovoljno') . " krvne grupe $grupa ($posto %)";
}



say ''; 	# FIXME DELME DEBUG
say decode('utf-8', $feed->as_xml);      # NB. XML::Atom is borken, see https://rt.cpan.org/Public/Bug/Display.html?id=43004 -- "$XML::Atom::ForceUnicode = 1" does not work for some reason, and even if it did this is safer as it is not global setting
