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
use CGI::Carp qw(fatalsToBrowser);
use Encode qw(decode);
use HTML::TreeBuilder::XPath;
use XML::Feed;
use IO::Handle;
use Fcntl ':flock';


my $q = new CGI;
my $VERSION = '2015-04-17';	# change script version here.
my $HZTM_URL = 'http://hztm.hr/hr/content/22/zalihe-krvi/831/zalihe-krvi';
my $HISTORY_DATA = 'krvne_grupe.history.txt';
my $HISTORY_TMP = $HISTORY_DATA . '.tmp';

#####################
#### CGI helpers ####
#####################

# validate params
sub _validate($$$)
{
  my ($param, $regex, $ok_null) = @_;
  my $value = $q->param($param);
  if (!defined($value)) {
    return undef if $ok_null;
    die "no param $param specified";
  }
  if ($value =~ /^(${regex})$/i) {
     $value = $1; 
     return $value;
  } 
  die "invalid value for param $param = $value";
}

sub validate($$)
{
  my ($param, $regex) = @_;
  return _validate ($param, $regex, 0);
}

sub validate_oknull($$)
{
  my ($param, $regex) = @_;
  return _validate ($param, $regex, 1);
}

#############################
#### validate CGI params ####
#############################

my $xml_feed = 'Atom';
my $mime = 'application/atom+xml';


if (validate_oknull('feed', 'RSS2?')) {
  $xml_feed = 'RSS';
  $mime = 'application/rss+xml';
}
my $krv_grupa = validate('grupa', '(0|A|B|AB)(minus|plus)'); 
$krv_grupa =~ s/minus/=/;
$krv_grupa =~ s/plus/+/;
$krv_grupa = uc($krv_grupa);

my $expires_seconds = 60*60*12;

print $q->header( -type => $mime, 
                  -charset=> 'utf-8',
                  -cache_control => "max-age=${expires_seconds}, public", 
                  -expires=> "+${expires_seconds}s",  
      );
                                                                                                                                                  
######################
#### generate RSS ####
######################

my $feed = XML::Feed->new($xml_feed);
my $TAG_BASE = 'tag:mnalis.com,2015-04-17:/hztm';	# DO NOT EDIT EVER!!
my $feed_id = "/HZTM-krv-unoff/$krv_grupa"; 
my $url = $q->url( -query => 1, -full => 1, -rewrite => 1);
$feed->self_link($url);
$feed->title( "Nedostatak krvne grupe $krv_grupa u HZTM" );
$feed->id( "$TAG_BASE/$feed_id" );
$feed->description( "Niske zalihe krvi grupe $krv_grupa (za dobrovoljne darivatelje krvi Hrvatskog zavoda za transfuzijsku medicinu)" );
$feed->language('hr');
$feed->copyright('Informacije su preuzete iz vanjskih izvora te ne odgovaramo za njihovu točnost');
$feed->author('mnalis-hztm@voyager.hr ( http://mnalis.com/hztm/ )');
$feed->generator("hztm_rss.cgi $VERSION using XML::Feed " . $XML::Feed::VERSION);
$feed->link($url);

# FIXME - polinkaj na mnalis.com/hztm mnalis.com
# FIXME - na mnalis.com/hztm stavi html formu da biras RSS/Atom i koju krvnu grupu. I link rel= isto za sve grupe..

my $last_timestamp = 0;
my $events_ref = [	# FIXME
  { opis => 'prva', grupa=>'A+', nedostaje => 1, datum => '2015-01-01', posto => 10, timestamp => time() },
  { opis => 'neka druga', grupa=>'B=', nedostaje => 0, datum => '2015-01-01', posto => 30, timestamp => time() },
];
foreach my $event (@$events_ref) {	# FIXME
    my $entry = XML::Feed::Entry->new($xml_feed);
    $entry->id( "$TAG_BASE/" . $event->{timestamp} . $feed_id );              # see http://taguri.org (RFC 4151), and http://web.archive.org/web/20110514113830/http://diveintomark.org/archives/2004/05/28/howto-atom-id
    $entry->link( $HZTM_URL );

    if ($event->{nedostaje}) {
        $entry->title( "$event->{datum} Nedostaje $event->{grupa} krvne grupe" );
        $entry->content( qq{Sa datumom $event->{datum} nedostaje krvne grupe $event->{grupa} (zalihe su samo $event->{posto}%). \nMolimo da se odazovete dobrovoljnom davanju krvi! \n\nHvala } );
    } else {
        $entry->title( "$event->{datum} Ponovno ima dovoljno krvne grupe $event->{grupa}" );
        $entry->content( qq{Sa datumom $event->{datum} ponovo ima dovoljno ($event->{posto}%) krvne grupe $event->{grupa} } );
    }
    
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

my %current = ();
my $c_timestamp = time;

for my $jedna (@sve) {
  my $c_posto = int ($jedna->findnodes( 'div[@class="outer"]/div[@class="inner"]' )->[0]->attr('data-percent'));
  my $ime = $jedna->findnodes( 'div[contains(concat(" ", normalize-space(@class), " "),"name")]' )->[0];
  my $c_grupa = $ime->content->[0];
  my $attr = $ime->attr('class');
  my $c_nedostaje = ($attr =~ /\bbig\b/);
  #say "grupa=$grupa, attr=$attr, nedostaje=$nedostaje, posto=$posto";
  say '' . ($c_nedostaje?'Nedostaje':'Ima dovoljno') . " krvne grupe $c_grupa ($c_posto %)";
  $current{$c_grupa} = { timestamp => $c_timestamp, grupa => $c_grupa, nedostaje => $c_nedostaje, posto => $c_posto };
}

##############################
#### update history files ####
##############################

# FIXME: separate .cgi and parsing HZTM / updating history file scripts (use common module for paths/filenames/lockfiles?)
#        or better: only use .cgi and do updating only if current_timestamp - history_file_timestamp > 24h ?
# FIXME: TODO - we need history files so we know if our value has changed!
# FIXME - perl-bloodgroup history files
# FIXME - beware of deadlock, but lock both IN and OUT!
# FIXME - flow: 
#		+ lock history file for reading
#		+ read it and cache in memory and find last state
#		+ if last state same as current, close and finish (autounlock)
#		+ otherwise, create temp file and lock it for writing
#		+ write cache to temp file
#		+ add new status to temp file
#		+ flush & sync temp file
#		+ rename temp file to history file
#		+ close temp file (autounlock) and input history file (autounlock)
#		- generate output RSS using cached data (and new status) [only for requested blood group!]
# FIXME - use global lock on non-changing readonly file for safety.

my $count = 0;
my @history = ();
my %zadnja = ();

        open my $IN, '<', $HISTORY_DATA or die "can't read $HISTORY_DATA: $!";
        flock($IN, LOCK_EX) or die "Could not lock $HISTORY_DATA: $!";
        open my $OUT, '>', $HISTORY_TMP or die "can't create $HISTORY_TMP: $!";
        flock($OUT, LOCK_EX) or die "Could not lock $HISTORY_TMP: $!";

        while (<$IN>) {
          chomp;
          my ($h_timestamp, $h_grupa, $h_nedostaje, $h_posto) = split /\t/;
          say "[$#history] $h_timestamp, $h_grupa, $h_nedostaje, $h_posto";
          push @history, { timestamp => $h_timestamp, grupa => $h_grupa, nedostaje => $h_nedostaje, posto => $h_posto };
          print $OUT "$h_timestamp\t$h_grupa\t$h_nedostaje\t$h_posto\n" or die "can't write to $HISTORY_TMP: $!";
          $zadnja{$h_grupa} = { timestamp => $h_timestamp, grupa => $h_grupa, nedostaje => $h_nedostaje, posto => $h_posto };
        }
        
        
        foreach my $k (keys %current) {
            say "current key $k($current{$k}{grupa}) => ($current{$k}{nedostaje}) $current{$k}{posto}%";
            if (!%zadnja or ($current{$k}{nedostaje} ne $zadnja{$k}{nedostaje})) {
                print $OUT "$current{$k}{timestamp}\t$current{$k}{grupa}\t$current{$k}{nedostaje}\t$current{$k}{posto}\n" or die "can't write to $HISTORY_TMP: $!";
            }
        }

# FIXME: DELME: DEBUG
#        use Data::Dumper;
#        say Dumper(\%current);        
#        say Dumper(\%zadnja);        
#....

        # hopefully this provides atomicity (but not durability, as we don't fsync dir after rename) -- see http://stackoverflow.com/questions/7433057/is-rename-without-fsync-safe & http://lwn.net/Articles/457667/
        $OUT->flush or die "can't flush $HISTORY_TMP: $!";
        $OUT->sync or die "can't fsync $HISTORY_TMP: $!";
        rename $HISTORY_TMP, $HISTORY_DATA or die "can't rename $HISTORY_TMP to $HISTORY_DATA: $!";
        close ($OUT) or die "can't close to $HISTORY_DATA: $!";



say ''; 	# FIXME DELME DEBUG
say decode('utf-8', $feed->as_xml);      # NB. XML::Atom is borken, see https://rt.cpan.org/Public/Bug/Display.html?id=43004 -- "$XML::Atom::ForceUnicode = 1" does not work for some reason, and even if it did this is safer as it is not global setting
