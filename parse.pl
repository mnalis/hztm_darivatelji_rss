#!/usr/bin/perl
# Matija Nalis <mnalis-git@voyager.hr> GPLv3+, started 2015-04-17
#
# detektira zalihe krvi u HZTMu, kako bi RSSom mogao dojaviti korisnicima kada neke krvne grupe nedostaje.
#

use strict;
use warnings;
use Carp qw(verbose);
use autodie;

use HTML::TreeBuilder::XPath;

my $FILE = 'zalihe-krvi';

#open my $f_in, '<', $FILE;
my $tree= HTML::TreeBuilder::XPath->new;
$tree->parse_file($FILE);

my @sve=$tree->findnodes( '/html/body//div[@id="supplies"]/div[contains(concat(" ", normalize-space(@class), " "),"measure")]' );

for my $jedna (@sve) {
  my $posto = int ($jedna->findnodes( 'div[@class="outer"]/div[@class="inner"]' )->[0]->attr('data-percent'));
  my $ime = $jedna->findnodes( 'div[contains(concat(" ", normalize-space(@class), " "),"name")]' )->[0];
  my $grupa = $ime->content->[0];
  my $attr = $ime->attr('class');
  my $nedostaje = ($attr =~ /\bbig\b/);
  #print "grupa=$grupa, attr=$attr, nedostaje=$nedostaje, posto=$posto\n";
  print '' . ($nedostaje?'Nedostaje':'Ima dovoljno') . " krvne grupe $grupa ($posto %)\n";
}
